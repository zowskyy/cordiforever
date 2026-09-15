"""Raw offline classification of frozen dev trajectories with the frozen Furthest-Reached Bottleneck methodology.

Analysis execution machinery (not methodology). It imports the frozen classifier unchanged, adds no semantics, and
writes only to the output directory given on the command line. No model access, no scorer execution.

Modes:
  classify --out DIR          preflight checks, classify, write DIR/classification.jsonl, DIR/summary.json, DIR/run_identity.json
  provenance --a DIR --b DIR --out DIR
                              require byte identity of the two independent runs, copy run A's artifacts to --out and
                              write --out/provenance.json (records artifact hashes; nothing depends on provenance)

Exit codes: 0 ok; 2 STOP (a condition outside the methodology's defined behavior, failed preflight or invariant).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

METHODOLOGY_COMMIT = "ed1e285bf49302f379476f60cb23533f0fd4d863"
METHODOLOGY = {
    "benchmark/analysis/furthest_bottleneck_taxonomy.md": "cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5",
    "benchmark/analysis/furthest_bottleneck.py": "6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b",
    "benchmark/analysis/furthest_bottleneck_mutations.py": "8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a",
    "tests/test_furthest_bottleneck.py": "055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451",
    "tests/test_furthest_bottleneck_mutations.py": "658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615",
}
DEPENDENCIES = ("benchmark/scoring/qwen_formatcontract_v1.py", "benchmark/scoring/qwen_selectorkind_v1.py")
HARNESS_MODULES = ("core/structured_edit.py", "core/diagnosis.py", "benchmark/repo_task_eval.py", "benchmark/repo_tasks.py", "core/path_candidates.py")
RESULTS = "benchmark/results/repo_task_eval.jsonl"
EXPECTED_RESULT_ROWS = 620
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


class Stop(Exception):
    """A condition outside the methodology's defined behavior, or a failed preflight/invariant."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(rel: str) -> str:
    return sha256_bytes((ROOT / rel).read_bytes())


def dumps_line(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


# ============================================================================= preflight
def preflight() -> dict[str, Any]:
    head = git("rev-parse", "HEAD")
    if head != METHODOLOGY_COMMIT:
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", METHODOLOGY_COMMIT, head], cwd=ROOT).returncode == 0
        changed = git("diff", "--name-only", f"{METHODOLOGY_COMMIT}..{head}", "--", *METHODOLOGY)
        if not ancestor or changed:
            raise Stop(f"HEAD {head} is not the methodology commit or a descendant without methodology changes")
    for rel, expected in METHODOLOGY.items():
        actual = sha256_file(rel)
        if actual != expected:
            raise Stop(f"methodology hash mismatch: {rel} {actual} != {expected}")
    results_bytes = (ROOT / RESULTS).read_bytes()
    committed = subprocess.run(["git", "show", f"HEAD:{RESULTS}"], cwd=ROOT, capture_output=True, check=True).stdout
    if results_bytes != committed:
        raise Stop("results file differs from HEAD")
    lines = results_bytes.decode("utf-8").splitlines()
    if sum(1 for line in lines if line.strip()) != EXPECTED_RESULT_ROWS:
        raise Stop("results file does not contain exactly 620 rows")
    return {
        "head": head,
        "methodology_commit": METHODOLOGY_COMMIT,
        "methodology_sha256": dict(METHODOLOGY),
        "dependency_sha256": {rel: sha256_file(rel) for rel in DEPENDENCIES},
        "harness_module_sha256": {rel: sha256_file(rel) for rel in HARNESS_MODULES},
        "results_sha256": sha256_bytes(results_bytes),
        "results_rows": EXPECTED_RESULT_ROWS,
        "runner_sha256": sha256_bytes(Path(__file__).resolve().read_bytes()),
        "python": sys.version.split()[0],
    }, lines


def select_arms(lines: list[str]) -> dict[str, list[tuple[int, dict[str, Any]]]]:
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
            raise Stop(f"{arm}: {len(arm_unsuccessful)} unsuccessful solvable rows, expected {EXPECTED['unsuccessful_per_arm']}")
        total += len(rows)
        solvable += len(arm_solvable)
        unsuccessful += len(arm_unsuccessful)
    if (total, solvable, unsuccessful) != (EXPECTED["rows"], EXPECTED["solvable"], EXPECTED["unsuccessful_solvable"]):
        raise Stop(f"population counts {total}/{solvable}/{unsuccessful} differ from 120/96/78")
    return selected


# ============================================================================= classification
def make_logging_replayer(fb):
    class LoggingReplayer(fb.OracleReplayer):
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


def oracle_sanity(fb) -> None:
    from benchmark.repo_tasks import TASKS_BY_NAME

    task = TASKS_BY_NAME["mathlib_divide_zero"]
    replayer = fb.OracleReplayer()
    if replayer.run(task, {})[0] is not fb.F:
        raise Stop("oracle sanity: seed state did not fail")
    if replayer.run(task, {"mathlib/operations.py": task.reference_patch["mathlib/operations.py"]})[0] is not fb.T:
        raise Stop("oracle sanity: reference patch did not pass")


def tri_str(value: Any) -> str:
    if value not in ("TRUE", "FALSE", "UNKNOWN") and getattr(value, "value", None) not in ("TRUE", "FALSE", "UNKNOWN"):
        raise Stop(f"non tri-state value encountered: {value!r}")
    return value if isinstance(value, str) else value.value


def classify_trajectory(fb, rte, normalize, arm: str, role: str, number: int, row: dict[str, Any]) -> dict[str, Any]:
    from benchmark.repo_tasks import TASKS_BY_NAME

    task = TASKS_BY_NAME.get(row["task"])
    if task is None:
        raise Stop(f"{arm}/{row.get('task')}: task not in the corpus definition")
    condition = row.get("condition")
    if condition not in rte.CONDITIONS:
        raise Stop(f"{arm}/{row['task']}: condition {condition!r} not defined")
    caps = fb.action_capabilities(rte.CONDITIONS[condition]["overrides"])
    replayer = make_logging_replayer(fb)()
    facts = fb.extract_facts(row, task, replayer, rte.defect_lines, rte.REPOS_DIR, normalize, caps)
    result = fb.classify(facts)
    _, _, d0_detail = fb.d0_task(task, caps, rte.REPOS_DIR, normalize)
    if result.label not in LABELS:
        raise Stop(f"{arm}/{row['task']}: label {result.label!r} outside the defined label set")
    proposals = [{
        "index": p.index, "path": p.path, "target": p.target,
        "D7_relevant": tri_str(p.relevant), "D8_resolves": tri_str(p.resolves), "D9_valid": tri_str(p.valid), "D10_accepted": tri_str(p.accepted),
        "stop_stage": p.stop_stage(), "result_head_sha256": sha256_bytes(p.result_head.encode("utf-8")),
        "guard_reason": p.guard_reason, "guard_judgement": p.guard_judgement,
    } for p in facts.proposals]
    return {
        "arm": arm, "arm_role": role, "condition": condition, "gate_sha256": ((row.get("experiment") or {}).get("gate") or {}).get("sha256"),
        "task": row["task"], "row_line": number, "row_fingerprint": row["fingerprint"],
        "label": result.label, "sub_label": result.sub_label,
        "d0_harness": tri_str(facts.d0_harness), "d0_contract": tri_str(facts.d0_contract), "d0_operation_classes": d0_detail,
        "facts": {
            "D1_D2_defect_known": tri_str(facts.defect_known), "D3_evidence": tri_str(facts.evidence),
            "D4_usable_diagnosis": tri_str(facts.usable_diagnosis), "D5_localized": tri_str(facts.localized),
            "diagnosis_attempted": tri_str(facts.diagnosis_attempted), "proposals": proposals,
            "R7": result.reach["R7"], "R8": result.reach["R8"], "R9": result.reach["R9"], "R10": result.reach["R10"],
            "D11_state_correct": [tri_str(v) for v in facts.state_correct], "D11_final_state": tri_str(facts.final_correct),
            "D12_regression_evidence": tri_str(facts.regression_evidence), "gold_edit_proposal_exists": facts.gold_edit_proposal_exists,
            "non_primitive_attempts": list(facts.non_primitive_attempts),
        },
        "history": list(result.history),
        "f5_guard": [list(g) for g in result.guard],
        "f6_subtype": result.f6_subtype if result.label == "F6" else None,
        "oracle_replays": replayer.log,
    }


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
            return {"n": n, "denominator": d, "fraction": f"{n}/{d}", "percent": round(100.0 * n / d, 1) if d else None}

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
            "interface_unsupported": {"count": counts["INTERFACE_UNSUPPORTED"], "tasks": [r["task"] for r in recs if r["label"] == "INTERFACE_UNSUPPORTED"]},
            "undetermined": {"count": counts["UNDETERMINED"], "tasks": [r["task"] for r in recs if r["label"] == "UNDETERMINED"],
                             "reasons": _count(r["sub_label"] for r in recs if r["label"] == "UNDETERMINED")},
            "d0_combinations": dict(sorted(combos.items())),
            "funnel": {
                "D3_evidence_TRUE": sum(1 for f in facts if f["D3_evidence"] == "TRUE"),
                "D5_localized_TRUE": sum(1 for f in facts if f["D5_localized"] == "TRUE"),
                "R7_TRUE": sum(1 for f in facts if f["R7"] == "TRUE"),
                "R8_TRUE": sum(1 for f in facts if f["R8"] == "TRUE"),
                "R9_TRUE": sum(1 for f in facts if f["R9"] == "TRUE"),
                "R10_TRUE": sum(1 for f in facts if f["R10"] == "TRUE"),
                "any_D11_TRUE": sum(1 for f in facts if "TRUE" in f["D11_state_correct"]),
            },
            "sub_labels": {label: _count(r["sub_label"] for r in recs if r["label"] == label) for label in ("F1", "F2", "F5")},
            "f5_guard_judgements": _count(g[1] for r in recs if r["label"] == "F5" for g in r["f5_guard"]),
            "f6_subtypes": _count(r["f6_subtype"] for r in recs if r["label"] == "F6"),
            "oracle_replays": sum(len(r["oracle_replays"]) for r in recs),
            "oracle_replay_errors": sum(1 for r in recs for o in r["oracle_replays"] if o["error"]),
        }
    primary = {r["task"]: r for r in by_arm["exp22_drift"]}
    agreement: dict[str, Any] = {}
    for arm, role, _condition, _gate in ARMS[1:]:
        other = {r["task"]: r for r in by_arm[arm]}
        tasks = sorted(set(primary) | set(other))
        disagreements = []
        same = 0
        for task in tasks:
            p, o = primary.get(task), other.get(task)
            if p and o and p["label"] == o["label"]:
                same += 1
                continue
            disagreements.append({"task": task, "primary_label": p["label"] if p else None, f"{role}_label": o["label"] if o else None,
                                  "primary_facts": _key_facts(p), f"{role}_facts": _key_facts(o)})
        agreement[arm] = {"role": role, "tasks_compared": len(tasks), "same_label": same, "disagreements": disagreements}
    return {"arms": arms_out, "agreement_with_primary": agreement}


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
    return {"d0_harness": rec["d0_harness"], "D1_D2": f["D1_D2_defect_known"], "D3": f["D3_evidence"], "D4": f["D4_usable_diagnosis"],
            "D5": f["D5_localized"], "R7": f["R7"], "R8": f["R8"], "R9": f["R9"], "R10": f["R10"],
            "D11_any_TRUE": "TRUE" in f["D11_state_correct"], "D11_final": f["D11_final_state"], "sub_label": rec["sub_label"]}


def run_classify(out: Path) -> int:
    identity, lines = preflight()
    selected = select_arms(lines)
    import benchmark.analysis.furthest_bottleneck as fb  # frozen dependency hashes are verified on first use
    from benchmark import repo_task_eval as rte
    from core.path_candidates import normalize

    fb.frozen_format_classifier()
    fb.frozen_edit_failure_reasons()
    oracle_sanity(fb)
    records = []
    for arm, role, _condition, _gate in ARMS:
        for number, row in sorted(selected[arm], key=lambda item: item[1]["task"]):
            if row.get("expected_outcome") != "verified_done" or row.get("oracle_passed") is True:
                continue
            try:
                records.append(classify_trajectory(fb, rte, normalize, arm, role, number, row))
            except Stop:
                raise
            except Exception as exc:  # outside defined behavior: stop, never continue around it
                raise Stop(f"{arm}/{row.get('task')} (line {number}): unexpected {type(exc).__name__}: {exc}") from exc
    if len(records) != EXPECTED["unsuccessful_solvable"]:
        raise Stop(f"classified {len(records)} trajectories, expected {EXPECTED['unsuccessful_solvable']}")
    classification = "".join(dumps_line(r) + "\n" for r in records)
    summary = json.dumps(summarize(records), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    out.mkdir(parents=True, exist_ok=False)
    (out / "classification.jsonl").write_text(classification, encoding="utf-8", newline="\n")
    (out / "summary.json").write_text(summary, encoding="utf-8", newline="\n")
    (out / "run_identity.json").write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"classification_sha256": sha256_bytes(classification.encode("utf-8")), "summary_sha256": sha256_bytes(summary.encode("utf-8")),
                      "runner_sha256": identity["runner_sha256"], "trajectories": len(records)}))
    return 0


def run_provenance(a: Path, b: Path, out: Path) -> int:
    names = ("classification.jsonl", "summary.json", "run_identity.json")
    hashes = {}
    for name in names:
        da, db = (a / name).read_bytes(), (b / name).read_bytes()
        if da != db:
            raise Stop(f"rerun identity failed: {name} differs between independent runs")
        hashes[name] = sha256_bytes(da)
    identity = json.loads((a / "run_identity.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    for name in ("classification.jsonl", "summary.json"):
        shutil.copyfile(a / name, out / name)
    summary = json.loads((a / "summary.json").read_text(encoding="utf-8"))
    provenance = {
        **identity,
        "arm_selectors": [{"arm": arm, "role": role, "condition": condition, "gate_sha256": gate, "split": "dev"} for arm, role, condition, gate in ARMS],
        "expected_population": EXPECTED,
        "classification_sha256": hashes["classification.jsonl"],
        "summary_sha256": hashes["summary.json"],
        "rerun_identity": {"independent_processes": 2, "byte_identical": True, "artifacts_compared": list(names)},
        "oracle_replays_total": sum(v["oracle_replays"] for v in summary["arms"].values()),
        "oracle_replay_errors_total": sum(v["oracle_replay_errors"] for v in summary["arms"].values()),
    }
    (out / "provenance.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"classification_sha256": hashes["classification.jsonl"], "summary_sha256": hashes["summary.json"],
                      "provenance_sha256": sha256_bytes((out / "provenance.json").read_bytes())}))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("provenance")
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return run_classify(args.out) if args.mode == "classify" else run_provenance(args.a, args.b, args.out)
    except Stop as stop:
        print(f"STOP: {stop}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
