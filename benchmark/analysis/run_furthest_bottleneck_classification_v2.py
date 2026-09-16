"""EXEC-D3V2-01 runner: apply the FROZEN D3-v2 methodology (MNT-08) to the preserved dev trajectories.

Execution tooling, not methodology. It imports the frozen D3-v2 module and changes nothing in it; the frozen v1
runner (`run_furthest_bottleneck_classification.py`) is untouched and remains the historical v1 execution.

Modes:
  classify --out DIR        preflight, classify, write DIR/{classification_v2.jsonl,summary_v2.json,
                            run_identity_v2.json,execution_provenance.json}. DIR must be a STAGING directory:
                            the runner refuses to write into the authoritative output tree.
  promote --a DIR --b DIR --out DIR
                            require byte identity of the SEMANTIC artifacts of two independent staged runs, then
                            create the authoritative output directory (which must not already exist) and write
                            classification_v2.jsonl, summary_v2.json and provenance_v2.json.
  transitions --v1 DIR --v2 DIR --out FILE
                            v1 -> v2 comparison, restricted to rows whose (arm, task, row_fingerprint) match
                            exactly; non-comparable rows are reported separately and never counted as transitions.

Byte identity is defined HERE, before any real execution, and is not revisited after seeing output:
  SEMANTIC (compared, must be byte-identical across the two processes):
      classification_v2.jsonl, summary_v2.json, run_identity_v2.json
  EXECUTION PROVENANCE (never compared, inherently process-specific):
      execution_provenance.json  - wall-clock times, pid, staging path, duration
`run_identity_v2.json` deliberately contains only deterministic fields (hashes, counts, versions); nothing
timestamp-, path- or process-derived is placed in it.

Fail-closed. Exit codes: 0 ok; 2 STOP (failed preflight, population mismatch, contract violation on a real row,
non-identical reruns, or any condition outside the frozen methodology's defined behavior).

Single registered execution: the two processes are two reproducibility realizations of ONE execution, never two
attempts to choose between.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FREEZE_COMMIT = "f30c5f6fee287774345e701041899668aaa3ec5d"
FREEZE_TAG = "d3-v2-methodology-freeze"

#: Category A - the frozen D3-v2 methodology. Pinned; a mismatch is a STOP.
METHODOLOGY_V2 = {
    "benchmark/analysis/furthest_bottleneck_taxonomy_v2.md": "4af9a3a414c3bf9ddad3a6f63190e4499f97387277349df9908a414a5e68abb2",
    "benchmark/analysis/furthest_bottleneck_v2.py": "e713ff4e99b967d3170ae8a41c9fc14eb706ae17065150424df0c085a923adef",
    "benchmark/analysis/furthest_bottleneck_v2_mutations.py": "4445c8e8d45e63008320da810ee3fe96bd9787afd09439af6b552bd67762b403",
    "tests/test_furthest_bottleneck_v2.py": "f2b897bb5a2dc16c61f0e582e7a2dc0b5dee2d6c5df4496a1c89534ff01f4725",
    "tests/test_producer_call_round_contract.py": "81c017bd162ada6c91f067cf28a9efa6e9c7a73e239bdc33c9e0737528af4205",
}
#: Frozen v1 - D3-v2 delegates every other fact to it, so it must be byte-identical too.
FROZEN_V1 = {
    "benchmark/analysis/furthest_bottleneck_taxonomy.md": "cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5",
    "benchmark/analysis/furthest_bottleneck.py": "6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b",
    "benchmark/analysis/furthest_bottleneck_mutations.py": "8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a",
    "tests/test_furthest_bottleneck.py": "055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451",
    "tests/test_furthest_bottleneck_mutations.py": "658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615",
}
#: Category B - frozen verification tooling. Not used at runtime; pinned as environment evidence.
VERIFICATION_TOOLING = {
    "benchmark/analysis/furthest_bottleneck_v2_property_search.py": "073e93abde94329a5e2d7009d163012a006cfe5e06a469604e8b3ffd880149d5",
    "benchmark/analysis/furthest_bottleneck_v2_producer_envelope_check.py": "e9c8eb3bf3ed7fb7fc571835ca486c0ea4c1ee055fdc031e1b5706b975ff881d",
}
DEPENDENCIES = ("benchmark/scoring/qwen_formatcontract_v1.py", "benchmark/scoring/qwen_selectorkind_v1.py")
HARNESS_MODULES = ("core/structured_edit.py", "core/diagnosis.py", "benchmark/repo_task_eval.py",
                   "benchmark/repo_tasks.py", "core/path_candidates.py")
RESULTS = "benchmark/results/repo_task_eval.jsonl"
RESULTS_SHA256 = "a242336f4e0b9fa3e467ad39a45b07e97f8994aa2591ffd46a545d4cd5b80978"
EXPECTED_RESULT_ROWS = 620
AUTHORITATIVE_OUTPUT = "benchmark/analysis/output_v2"
V1_OUTPUT = "benchmark/analysis/output"

#: Population definition, reproduced from the v1 runner so the same rows are selected, not a new population.
ARMS = (  # (arm id, role, condition, gate sha256) in reporting order
    ("exp22_drift", "primary", "qwen_selectorkind", "13e9a05bef83e51bdeb8acc4119f8db8e9755c5850ebfea6f9755fe32654a218"),
    ("exp18_treatment", "identity", "qwen_selectorkind", "dcca9c02e0aee827005043ca08b4b617d4f88c7a3a048b69a975f20572f51e47"),
    ("exp20_drift", "identity", "qwen_selectorkind", "ba0790c8e96b4ec2cb8dff5dd099981fae1d5aae8a1cb4c281dbd463938e29d4"),
    ("exp20_treatment", "perturbation", "qwen_astnoop", "ba0790c8e96b4ec2cb8dff5dd099981fae1d5aae8a1cb4c281dbd463938e29d4"),
    ("exp21_treatment", "perturbation", "qwen_donelatch", "b7bb6338179aad39c4181ad8ca6f4cbaf02ca9f1c6b12aa9261e9c1b8bd748f6"),
    ("exp22_treatment", "perturbation", "qwen_formatcontract", "13e9a05bef83e51bdeb8acc4119f8db8e9755c5850ebfea6f9755fe32654a218"),
)
EXPECTED = {"rows_per_arm": 20, "rows": 120, "solvable": 96, "unsuccessful_solvable": 78, "unsuccessful_per_arm": 13}
LABELS = {"F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "INTERFACE_UNSUPPORTED", "UNDETERMINED"}
BOTTLENECK = ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
SEMANTIC_ARTIFACTS = ("classification_v2.jsonl", "summary_v2.json", "run_identity_v2.json")
EXECUTION_PROVENANCE = "execution_provenance.json"


class Stop(Exception):
    """A condition outside the frozen methodology's defined behavior, or a failed preflight/invariant."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(rel: str) -> str:
    return sha256_bytes((ROOT / rel).read_bytes())


def dumps_line(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


# ============================================================================= preflight
def preflight() -> tuple[dict[str, Any], list[str]]:
    """Every frozen input is verified before a single real row is parsed."""
    head = git("rev-parse", "HEAD")
    frozen_paths = [*METHODOLOGY_V2, *FROZEN_V1, *VERIFICATION_TOOLING]
    if head != FREEZE_COMMIT:
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", FREEZE_COMMIT, head], cwd=ROOT).returncode == 0
        changed = git("diff", "--name-only", f"{FREEZE_COMMIT}..{head}", "--", *frozen_paths)
        if not ancestor or changed:
            raise Stop(f"HEAD {head} is not the freeze commit or a descendant that leaves frozen artifacts unchanged")
    for group, pinned in (("methodology_v2", METHODOLOGY_V2), ("frozen_v1", FROZEN_V1),
                          ("verification_tooling", VERIFICATION_TOOLING)):
        for rel, expected in pinned.items():
            actual = sha256_file(rel)
            if actual != expected:
                raise Stop(f"{group} hash mismatch: {rel} {actual} != {expected}")
    results_bytes = (ROOT / RESULTS).read_bytes()
    committed = subprocess.run(["git", "show", f"HEAD:{RESULTS}"], cwd=ROOT, capture_output=True, check=True).stdout
    if results_bytes != committed:
        raise Stop("results file differs from HEAD")
    results_sha = sha256_bytes(results_bytes)
    if results_sha != RESULTS_SHA256:
        raise Stop(f"results file sha256 {results_sha} != registered {RESULTS_SHA256}")
    lines = results_bytes.decode("utf-8").splitlines()
    if sum(1 for line in lines if line.strip()) != EXPECTED_RESULT_ROWS:
        raise Stop(f"results file does not contain exactly {EXPECTED_RESULT_ROWS} rows")
    identity = {
        "execution_id": "EXEC-D3V2-01",
        "methodology": "D3-v2 (MNT-08)",
        "freeze_tag": FREEZE_TAG,
        "freeze_commit": FREEZE_COMMIT,
        "head": head,
        "methodology_v2_sha256": dict(METHODOLOGY_V2),
        "frozen_v1_sha256": dict(FROZEN_V1),
        "verification_tooling_sha256": dict(VERIFICATION_TOOLING),
        "dependency_sha256": {rel: sha256_file(rel) for rel in DEPENDENCIES},
        "harness_module_sha256": {rel: sha256_file(rel) for rel in HARNESS_MODULES},
        "results_sha256": results_sha,
        "results_rows": EXPECTED_RESULT_ROWS,
        "runner_sha256": sha256_bytes(Path(__file__).resolve().read_bytes()),
        "python": sys.version.split()[0],
        "expected_population": dict(EXPECTED),
        "arms": [{"arm": a, "role": r, "condition": c, "gate_sha256": g, "split": "dev"} for a, r, c, g in ARMS],
        "byte_identity": {"semantic_artifacts": list(SEMANTIC_ARTIFACTS),
                          "execution_provenance_excluded": EXECUTION_PROVENANCE},
    }
    return identity, lines


def select_arms(lines: list[str]) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """v1's selection rule, unchanged: the same rows, reconstructed rather than redefined."""
    from benchmark.repo_tasks import TASKS

    dev_tasks = {t.name for t in TASKS if t.split == "dev"}
    selected: dict[str, list[tuple[int, dict[str, Any]]]] = {arm: [] for arm, *_ in ARMS}
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        gate = ((row.get("experiment") or {}).get("gate") or {}).get("sha256")
        for arm, _role, condition, gate_sha in ARMS:
            if row.get("split") == "dev" and row.get("condition") == condition and gate == gate_sha:
                selected[arm].append((number, row))
    total = solvable = unsuccessful = 0
    for arm, _role, _condition, _gate in ARMS:
        rows = selected[arm]
        tasks = [r["task"] for _, r in rows]
        if len(rows) != EXPECTED["rows_per_arm"]:
            raise Stop(f"{arm}: {len(rows)} rows selected, expected {EXPECTED['rows_per_arm']}")
        if len(set(tasks)) != len(tasks):
            raise Stop(f"{arm}: duplicate task rows")
        if set(tasks) != dev_tasks:
            raise Stop(f"{arm}: task set differs from the dev task set")
        if any(not r.get("fingerprint") for _, r in rows):
            raise Stop(f"{arm}: row without fingerprint")
        arm_solvable = [r for _, r in rows if r.get("expected_outcome") == "verified_done"]
        arm_unsuccessful = [r for r in arm_solvable if r.get("oracle_passed") is not True]
        if len(arm_unsuccessful) != EXPECTED["unsuccessful_per_arm"]:
            raise Stop(f"{arm}: {len(arm_unsuccessful)} unsuccessful solvable rows, "
                       f"expected {EXPECTED['unsuccessful_per_arm']}")
        total += len(rows)
        solvable += len(arm_solvable)
        unsuccessful += len(arm_unsuccessful)
    if (total, solvable, unsuccessful) != (EXPECTED["rows"], EXPECTED["solvable"], EXPECTED["unsuccessful_solvable"]):
        raise Stop(f"population counts {total}/{solvable}/{unsuccessful} differ from "
                   f"{EXPECTED['rows']}/{EXPECTED['solvable']}/{EXPECTED['unsuccessful_solvable']}")
    return selected


# ============================================================================= classification
def make_logging_replayer(v1):
    class LoggingReplayer(v1.OracleReplayer):
        """Records each replay request; calls the frozen OracleReplayer.run unchanged."""

        def __init__(self) -> None:
            super().__init__()
            self.log: list[dict[str, Any]] = []

        def run(self, task, files):
            verdict, detail = super().run(task, files)
            passed = re.search(r"(\d+) passed", detail or "")
            failed = re.search(r"(\d+) failed", detail or "")
            self.log.append({
                "files_state_sha256": sha256_bytes(json.dumps(sorted(files.items()), default=str).encode("utf-8")),
                "verdict": verdict.value,
                "passed": int(passed.group(1)) if passed else None,
                "failed": int(failed.group(1)) if failed else None,
                "error": bool(detail) and (detail.startswith("oracle error") or "oracle timed out" in detail),
            })
            return verdict, detail

    return LoggingReplayer


def oracle_sanity(v1) -> None:
    from benchmark.repo_tasks import TASKS_BY_NAME

    task = TASKS_BY_NAME["mathlib_divide_zero"]
    replayer = v1.OracleReplayer()
    if replayer.run(task, {})[0] is not v1.F:
        raise Stop("oracle sanity: seed state did not fail")
    if replayer.run(task, {"mathlib/operations.py": task.reference_patch["mathlib/operations.py"]})[0] is not v1.T:
        raise Stop("oracle sanity: reference patch did not pass")


def tri_str(value: Any) -> str:
    if value not in ("TRUE", "FALSE", "UNKNOWN") and getattr(value, "value", None) not in ("TRUE", "FALSE", "UNKNOWN"):
        raise Stop(f"non tri-state value encountered: {value!r}")
    return value if isinstance(value, str) else value.value


def classify_trajectory(v1, v2, rte, normalize, arm: str, role: str, number: int, row: dict[str, Any]) -> dict[str, Any]:
    from benchmark.repo_tasks import TASKS_BY_NAME

    task = TASKS_BY_NAME.get(row["task"])
    if task is None:
        raise Stop(f"{arm}/{row.get('task')}: task not in the corpus definition")
    condition = row.get("condition")
    if condition not in rte.CONDITIONS:
        raise Stop(f"{arm}/{row['task']}: condition {condition!r} not defined")
    caps = v1.action_capabilities(rte.CONDITIONS[condition]["overrides"])
    replayer = make_logging_replayer(v1)()
    try:
        facts, descriptive = v2.extract_facts_v2(row, task, replayer, rte.defect_lines, rte.REPOS_DIR, normalize, caps)
    except v2.RowContractViolation as violation:
        # A real row outside the frozen input contract is NOT a classification. Record who it was and stop.
        raise Stop(json.dumps({"contract_violation": {
            "arm": arm, "arm_role": role, "task": row.get("task"), "row_line": number,
            "row_fingerprint": row.get("fingerprint"), "condition": condition,
            "contract": getattr(violation, "contract", None),
            "violation_type": type(violation).__name__, "detail": getattr(violation, "detail", str(violation)),
        }}, sort_keys=True)) from violation
    result = v2.classify(facts)
    _, _, d0_detail = v1.d0_task(task, caps, rte.REPOS_DIR, normalize)
    if result.label not in LABELS:
        raise Stop(f"{arm}/{row['task']}: label {result.label!r} outside the defined label set")
    scope = v2.d1_region_files(task, rte.REPOS_DIR, rte.defect_lines, normalize)
    proposals = [{
        "index": p.index, "path": p.path, "target": p.target,
        "D7_relevant": tri_str(p.relevant), "D8_resolves": tri_str(p.resolves),
        "D9_valid": tri_str(p.valid), "D10_accepted": tri_str(p.accepted),
        "stop_stage": p.stop_stage(), "result_head_sha256": sha256_bytes(p.result_head.encode("utf-8")),
        "guard_reason": p.guard_reason, "guard_judgement": p.guard_judgement,
    } for p in facts.proposals]
    return {
        "methodology": "D3-v2",
        "arm": arm, "arm_role": role, "condition": condition,
        "gate_sha256": ((row.get("experiment") or {}).get("gate") or {}).get("sha256"),
        "task": row["task"], "row_line": number, "row_fingerprint": row["fingerprint"],
        "label": result.label, "sub_label": result.sub_label,
        "d0_harness": tri_str(facts.d0_harness), "d0_contract": tri_str(facts.d0_contract),
        "d0_operation_classes": d0_detail,
        "d3_scope": list(scope),
        "d3_per_file": {g: tri_str(v2.d3_file(row, g, normalize)) for g in scope},
        "d3_bounds_per_file": {g: [str(b) for b in v2.cutoff_bounds(row, g, normalize)] for g in scope},
        "descriptive_facts": dict(descriptive),
        "facts": {
            "D1_D2_defect_known": tri_str(facts.defect_known), "D3_evidence": tri_str(facts.evidence),
            "D4_usable_diagnosis": tri_str(facts.usable_diagnosis), "D5_localized": tri_str(facts.localized),
            "diagnosis_attempted": tri_str(facts.diagnosis_attempted), "proposals": proposals,
            "R7": result.reach["R7"], "R8": result.reach["R8"], "R9": result.reach["R9"], "R10": result.reach["R10"],
            "D11_state_correct": [tri_str(v) for v in facts.state_correct],
            "D11_final_state": tri_str(facts.final_correct),
            "D12_regression_evidence": tri_str(facts.regression_evidence),
            "gold_edit_proposal_exists": facts.gold_edit_proposal_exists,
            "non_primitive_attempts": list(facts.non_primitive_attempts),
        },
        "history": list(result.history),
        "f5_guard": [list(g) for g in result.guard],
        "f6_subtype": result.f6_subtype if result.label == "F6" else None,
        "oracle_replays": replayer.log,
    }


# ============================================================================= summary
def _count(values) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        key = str(v)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _key_facts(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    if rec is None:
        return None
    f = rec["facts"]
    return {"d0_harness": rec["d0_harness"], "D1_D2": f["D1_D2_defect_known"], "D3": f["D3_evidence"],
            "D4": f["D4_usable_diagnosis"], "D5": f["D5_localized"], "R7": f["R7"], "R8": f["R8"],
            "R9": f["R9"], "R10": f["R10"], "D11_any_TRUE": "TRUE" in f["D11_state_correct"],
            "D11_final": f["D11_final_state"], "sub_label": rec["sub_label"]}


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm, *_ in ARMS}
    for rec in records:
        by_arm[rec["arm"]].append(rec)
    arms_out: dict[str, Any] = {}
    for arm, role, condition, gate in ARMS:
        recs = sorted(by_arm[arm], key=lambda r: r["task"])
        counts = {label: sum(1 for r in recs if r["label"] == label) for label in sorted(LABELS)}
        denominator = sum(counts[label] for label in BOTTLENECK)

        def share(n: int, d: int) -> dict[str, Any]:
            return {"n": n, "denominator": d, "fraction": f"{n}/{d}",
                    "percent": round(100.0 * n / d, 1) if d else None}

        combos: dict[str, int] = {}
        for r in recs:
            key = f"HARNESS_{r['d0_harness']}/CONTRACT_{r['d0_contract']}"
            combos[key] = combos.get(key, 0) + 1
        facts = [r["facts"] for r in recs]
        arms_out[arm] = {
            "role": role, "condition": condition, "gate_sha256": gate, "trajectories": len(recs),
            "label_counts": counts,
            "bottleneck_denominator_F0_F8": denominator,
            "bottleneck_shares": {label: share(counts[label], denominator) for label in BOTTLENECK},
            "interface_unsupported": {"count": counts["INTERFACE_UNSUPPORTED"],
                                      "tasks": [r["task"] for r in recs if r["label"] == "INTERFACE_UNSUPPORTED"]},
            "undetermined": {"count": counts["UNDETERMINED"],
                             "tasks": [r["task"] for r in recs if r["label"] == "UNDETERMINED"],
                             "reasons": _count(r["sub_label"] for r in recs if r["label"] == "UNDETERMINED")},
            "d0_combinations": dict(sorted(combos.items())),
            "d3": {
                "TRUE": sum(1 for f in facts if f["D3_evidence"] == "TRUE"),
                "FALSE": sum(1 for f in facts if f["D3_evidence"] == "FALSE"),
                "UNKNOWN": sum(1 for f in facts if f["D3_evidence"] == "UNKNOWN"),
            },
            "descriptive_facts": {
                "D3_ATTEMPT_OBSERVED": _count(r["descriptive_facts"]["D3_ATTEMPT_OBSERVED"] for r in recs),
                "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT": _count(
                    r["descriptive_facts"]["D3_OBSERVED_PRE_EVIDENCE_ATTEMPT"] for r in recs),
            },
            "funnel": {
                "D3_evidence_TRUE": sum(1 for f in facts if f["D3_evidence"] == "TRUE"),
                "D5_localized_TRUE": sum(1 for f in facts if f["D5_localized"] == "TRUE"),
                "R7_TRUE": sum(1 for f in facts if f["R7"] == "TRUE"),
                "R8_TRUE": sum(1 for f in facts if f["R8"] == "TRUE"),
                "R9_TRUE": sum(1 for f in facts if f["R9"] == "TRUE"),
                "R10_TRUE": sum(1 for f in facts if f["R10"] == "TRUE"),
                "any_D11_TRUE": sum(1 for f in facts if "TRUE" in f["D11_state_correct"]),
            },
            "sub_labels": {label: _count(r["sub_label"] for r in recs if r["label"] == label)
                           for label in ("F1", "F2", "F5")},
            "f5_guard_judgements": _count(g[1] for r in recs if r["label"] == "F5" for g in r["f5_guard"]),
            "f6_subtypes": _count(r["f6_subtype"] for r in recs if r["label"] == "F6"),
            "oracle_replays": sum(len(r["oracle_replays"]) for r in recs),
            "oracle_replay_errors": sum(1 for r in recs for o in r["oracle_replays"] if o["error"]),
        }
    primary = {r["task"]: r for r in by_arm["exp22_drift"]}
    agreement: dict[str, Any] = {}
    for arm, role, _condition, _gate in ARMS[1:]:
        other = {r["task"]: r for r in by_arm[arm]}
        shared = sorted(set(primary) & set(other))
        only_primary = sorted(set(primary) - set(other))
        only_other = sorted(set(other) - set(primary))
        disagreements = [{"task": t, "primary_label": primary[t]["label"], f"{role}_label": other[t]["label"],
                          "primary_facts": _key_facts(primary[t]), f"{role}_facts": _key_facts(other[t])}
                         for t in shared if primary[t]["label"] != other[t]["label"]]
        agreement[arm] = {
            "role": role,
            "comparable_tasks": len(shared),
            "same_label": len(shared) - len(disagreements),
            "disagreements": disagreements,
            # membership differences are NOT label transitions; they are reported on their own
            "membership_difference": {"only_in_primary": only_primary, "only_in_this_arm": only_other},
        }
    return {"methodology": "D3-v2", "arms": arms_out, "agreement_with_primary": agreement,
            "interpretation_notes": [
                "Identity arms are call-for-call identical temperature-0 traces; agreement is determinism evidence, "
                "not independent replication.",
                "Membership differences are reported separately and are never counted as label transitions.",
                "No bottleneck is designated from frequency alone; ties are reported as ties.",
            ]}


# ============================================================================= modes
def run_classify(out: Path) -> int:
    authoritative = (ROOT / AUTHORITATIVE_OUTPUT).resolve()
    resolved = out.resolve()
    if resolved == authoritative or authoritative in resolved.parents:
        raise Stop(f"--out must be a staging directory; refusing to write inside {AUTHORITATIVE_OUTPUT}")
    started = time.time()
    identity, lines = preflight()
    selected = select_arms(lines)
    import benchmark.analysis.furthest_bottleneck as v1
    import benchmark.analysis.furthest_bottleneck_v2 as v2
    from benchmark import repo_task_eval as rte
    from core.path_candidates import normalize

    v1.frozen_format_classifier()
    v1.frozen_edit_failure_reasons()
    oracle_sanity(v1)
    records = []
    for arm, role, _condition, _gate in ARMS:
        for number, row in sorted(selected[arm], key=lambda item: item[1]["task"]):
            if row.get("expected_outcome") != "verified_done" or row.get("oracle_passed") is True:
                continue
            try:
                records.append(classify_trajectory(v1, v2, rte, normalize, arm, role, number, row))
            except Stop:
                raise
            except Exception as exc:  # outside defined behavior: stop, never continue around it
                raise Stop(f"{arm}/{row.get('task')} (line {number}): unexpected {type(exc).__name__}: {exc}") from exc
    if len(records) != EXPECTED["unsuccessful_solvable"]:
        raise Stop(f"classified {len(records)} trajectories, expected {EXPECTED['unsuccessful_solvable']}")
    classification = "".join(dumps_line(r) + "\n" for r in records)
    summary = json.dumps(summarize(records), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    out.mkdir(parents=True, exist_ok=False)
    _write(out / "classification_v2.jsonl", classification)
    _write(out / "summary_v2.json", summary)
    _write(out / "run_identity_v2.json", json.dumps(identity, sort_keys=True, indent=2) + "\n")
    _write(out / EXECUTION_PROVENANCE, json.dumps({          # never compared for byte identity
        "execution_id": "EXEC-D3V2-01", "staging_path": str(resolved), "pid": os.getpid(),
        "started_unix": round(started, 3), "finished_unix": round(time.time(), 3),
        "duration_seconds": round(time.time() - started, 3),
    }, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"classification_sha256": sha256_bytes(classification.encode("utf-8")),
                      "summary_sha256": sha256_bytes(summary.encode("utf-8")),
                      "runner_sha256": identity["runner_sha256"], "trajectories": len(records)}))
    return 0


def run_promote(a: Path, b: Path, out: Path) -> int:
    """Promote only after both staged runs agree byte-for-byte on every SEMANTIC artifact."""
    hashes = {}
    for name in SEMANTIC_ARTIFACTS:
        da, db = (a / name).read_bytes(), (b / name).read_bytes()
        if da != db:
            raise Stop(f"determinism gate failed: {name} differs between the two independent runs; "
                       f"neither result is authoritative and nothing is promoted "
                       f"(A sha256 {sha256_bytes(da)[:12]}, B sha256 {sha256_bytes(db)[:12]})")
        hashes[name] = sha256_bytes(da)
    if out.exists():
        raise Stop(f"authoritative output already exists: {out} (v2 output is written once and never overwritten)")
    identity = json.loads((a / "run_identity_v2.json").read_text(encoding="utf-8"))
    summary = json.loads((a / "summary_v2.json").read_text(encoding="utf-8"))
    staging = out.parent / f".{out.name}.incoming"      # build fully, then move into place
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for name in ("classification_v2.jsonl", "summary_v2.json", "run_identity_v2.json"):
        shutil.copyfile(a / name, staging / name)
    provenance = {
        **identity,
        "classification_sha256": hashes["classification_v2.jsonl"],
        "summary_sha256": hashes["summary_v2.json"],
        "run_identity_sha256": hashes["run_identity_v2.json"],
        "rerun_identity": {"independent_processes": 2, "byte_identical": True,
                           "artifacts_compared": list(SEMANTIC_ARTIFACTS),
                           "artifacts_excluded": [EXECUTION_PROVENANCE]},
        "oracle_replays_total": sum(v["oracle_replays"] for v in summary["arms"].values()),
        "oracle_replay_errors_total": sum(v["oracle_replay_errors"] for v in summary["arms"].values()),
        "v1_output_untouched": V1_OUTPUT,
    }
    _write(staging / "provenance_v2.json", json.dumps(provenance, sort_keys=True, indent=2) + "\n")
    os.replace(staging, out)
    print(json.dumps({"promoted": str(out), **{k: v for k, v in hashes.items()},
                      "provenance_sha256": sha256_bytes((out / "provenance_v2.json").read_bytes())}))
    return 0


def run_transitions(v1_dir: Path, v2_dir: Path, out: Path) -> int:
    """v1 -> v2 comparison on rows whose (arm, task, row_fingerprint) match exactly. v1 output is read-only."""
    def load(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
        records = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                records[(r["arm"], r["task"], r.get("row_fingerprint"))] = r
        return records

    old, new = load(v1_dir / "classification.jsonl"), load(v2_dir / "classification_v2.jsonl")
    comparable = sorted(set(old) & set(new))
    transitions = _count(f"{old[k]['label']}->{new[k]['label']}" for k in comparable)
    d3_transitions = _count(f"{old[k]['facts']['D3_evidence']}->{new[k]['facts']['D3_evidence']}" for k in comparable)
    changed = [{"arm": k[0], "task": k[1], "v1_label": old[k]["label"], "v2_label": new[k]["label"],
                "v1_sub_label": old[k]["sub_label"], "v2_sub_label": new[k]["sub_label"],
                "v1_D3": old[k]["facts"]["D3_evidence"], "v2_D3": new[k]["facts"]["D3_evidence"]}
               for k in comparable if old[k]["label"] != new[k]["label"]]
    report = {
        "comparable_rows": len(comparable),
        "non_comparable": {"only_in_v1": [list(k) for k in sorted(set(old) - set(new))],
                           "only_in_v2": [list(k) for k in sorted(set(new) - set(old))]},
        "label_transitions": transitions,
        "d3_evidence_transitions": d3_transitions,
        "changed_rows": changed,
        "notes": ["Rows are compared only when arm, task and row fingerprint all match; membership differences are "
                  "listed under non_comparable and are never counted as transitions.",
                  "A transition is a methodology difference, not an improvement: more determined classifications is "
                  "not a quality claim."],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    _write(out, json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"comparable_rows": len(comparable), "label_transitions": transitions,
                      "report": str(out)}))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="EXEC-D3V2-01 runner (frozen D3-v2 applied to preserved rows)")
    sub = parser.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--out", type=Path, required=True, help="staging directory; must be outside the authoritative tree")
    p = sub.add_parser("promote")
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("transitions")
    t.add_argument("--v1", type=Path, required=True)
    t.add_argument("--v2", type=Path, required=True)
    t.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "classify":
            return run_classify(args.out)
        if args.mode == "promote":
            return run_promote(args.a, args.b, args.out)
        return run_transitions(args.v1, args.v2, args.out)
    except Stop as stop:
        print(f"STOP: {stop}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
