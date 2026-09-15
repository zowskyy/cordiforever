"""Scorer for gate qwen_extract_v1 (benchmark/gates/qwen_extract_v1.md).

Written and hash-logged in EXPERIMENT_LOG.md before any qwen_extract_v1 run. Every gate clause maps to one computed
field; the verdict uses only those fields. Do not edit after results exist: a change is a new scorer file with its
own recorded hash.

Arms:
  control   = frozen `qwen_evidence` rows carrying the qwen_evidence_v1 gate sha256
  drift     = `qwen_evidence` rerun rows carrying the qwen_extract_v1 gate sha256 (flag off, new harness)
  treatment = `qwen_extract` rows carrying the qwen_extract_v1 gate sha256

Pairing (no fallback): diagnose records <-> diagnose calls positionally, with count, path and success checks;
successful read_file calls <-> read_views positionally, with count and path checks. Any violation raises.

Usage:  .venv\\Scripts\\python.exe benchmark\\scoring\\qwen_extract_v1.py
Writes: benchmark/results/qwen_extract_v1_frozen.json
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmark import repo_task_eval as rte  # noqa: E402
from benchmark.repo_tasks import TASKS_BY_NAME  # noqa: E402
from core.path_candidates import normalize  # noqa: E402

GATE = ROOT / "benchmark" / "gates" / "qwen_extract_v1.md"
CONTROL_GATE_SHA = "4ba9b011d6944b0bf10419d93e96bf8ec5f52fbdb1b1a9beb45946ef07a7d45d"  # qwen_evidence_v1
RESULTS = ROOT / "benchmark" / "results" / "repo_task_eval.jsonl"
OUT = ROOT / "benchmark" / "results" / "qwen_extract_v1_frozen.json"
PRIMARY_MIN_LOCALIZED_HITS = 3
DRIFT_TOLERANCE = 1
EXPECTED_ROWS = 20
NO_SPAN_REASONS = {
    "not_python_symbol": "is not a function, class, method or assignment defined in",
    "json_pointer_unresolved": "does not resolve in",
    "unsupported_file_type": "evidence targets are supported only for",
    "no_complete_read": "has no complete read in this task",
    "missing_cause_or_change": "needs a cause and a change",
}


class PairingError(ValueError):
    """A positional pairing invariant does not hold for a row."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows() -> list[dict[str, Any]]:
    return [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line.strip()]


def select(rows: list[dict[str, Any]], condition: str, gate_sha: str) -> dict[str, dict[str, Any]]:
    by_task: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("condition") == condition and r.get("split") == "dev" and ((r.get("experiment") or {}).get("gate") or {}).get("sha256") == gate_sha:
            by_task[r["task"]] = r
    return by_task


def paired_diagnoses(row: dict[str, Any]) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    calls = [c for c in row["calls"] if c["tool"] == "diagnose"]
    records = list(row["diagnoses"])
    if len(records) != len(calls):
        raise PairingError(f"{row['task']}: {len(records)} diagnose records vs {len(calls)} diagnose results")
    pairs = []
    for index, (record, call) in enumerate(zip(records, calls)):
        call_path = normalize(str(call["args"].get("path") or ""))
        if record["path"] != call_path:
            raise PairingError(f"{row['task']} diagnose pair {index}: record path {record['path']!r} != call path {call_path!r}")
        if record.get("refused") is None and bool(record["success"]) != bool(call["success"]):
            raise PairingError(f"{row['task']} diagnose pair {index}: record success {record['success']} != call success {call['success']}")
        if record.get("refused") is not None and call["success"]:
            raise PairingError(f"{row['task']} diagnose pair {index}: guard-refused record paired with a successful call")
        pairs.append((index, record, call))
    return pairs


def extraction_without_prior_full_read(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Successful selector diagnoses with no earlier complete read view of the same path (timeline order)."""
    reads = [c for c in row["calls"] if c["tool"] == "read_file" and c["success"]]
    views = list(row["read_views"])
    if len(reads) != len(views):
        raise PairingError(f"{row['task']}: {len(reads)} successful reads vs {len(views)} read views")
    for index, (call, view) in enumerate(zip(reads, views)):
        if normalize(str(call["args"].get("path") or "")) != view["path"]:
            raise PairingError(f"{row['task']} read pair {index}: call path != view path {view['path']!r}")
    diagnose_pairs = iter(paired_diagnoses(row))
    view_iter = iter(views)
    complete: set[str] = set()
    violations = []
    for call in row["calls"]:
        if call["tool"] == "read_file" and call["success"]:
            view = next(view_iter)
            if view["complete"] is True:
                complete.add(view["path"])
        elif call["tool"] == "diagnose":
            index, record, _ = next(diagnose_pairs)
            if record.get("refused") is None and record["success"] and record.get("target") is not None and record["path"] not in complete:
                violations.append({"task": row["task"], "pair_index": index, "path": record["path"]})
    return violations


def no_span_reason(call: dict[str, Any]) -> str:
    head = call.get("result_head", "")
    matches = [key for key, text in NO_SPAN_REASONS.items() if text in head]
    return matches[0] if len(matches) == 1 else "other"


def arm_fields(by_task: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = list(by_task.values())
    solvable = [r for r in rows if r["expected_outcome"] == "verified_done"]
    insufficient = [r for r in rows if r["expected_outcome"] == "escalate"]
    summary = rte.summarize_condition(rows)
    pairs = [(r, i, rec, call) for r in solvable for i, rec, call in paired_diagnoses(r)]
    executed = [(r, i, rec, call) for r, i, rec, call in pairs if rec.get("refused") is None]
    successful = [(r, i, rec, call) for r, i, rec, call in executed if rec["success"]]
    failed = [(r, i, rec, call) for r, i, rec, call in executed if not rec["success"]]
    spans = [rec["seed_span"][1] - rec["seed_span"][0] + 1 for _, _, rec, _ in successful if rec.get("seed_span")]
    localized_hits = sum(1 for _, _, rec, _ in successful if rec.get("hits_defect_localized"))
    progress = {r["task"]: rte.progress_metrics(r, TASKS_BY_NAME[r["task"]], rte.repo_files(rte.REPOS_DIR / TASKS_BY_NAME[r["task"]].repo)) for r in rows}
    return {
        # validity
        "rows": len(rows), "solvable_rows": len(solvable),
        "invalid_solvable_rows": sum(1 for r in solvable if r["truncated_read_views"] != 0),
        "harness_sha256": sorted({r["experiment"]["harness_sha256"] for r in rows}),
        "model_digest": sorted({r["experiment"]["model_digest"] for r in rows}),
        # primary
        "tasks_with_localized_hit": sum(1 for r in solvable if any(d.get("hits_defect_localized") for d in r["diagnoses"])),
        # guardrails
        "lane_false_verified": summary["lane_false_verified"],
        "false_completion_on_insufficient_evidence": sum(1 for r in insufficient if r["false_completion_on_insufficient_evidence"]),
        "damaged_file_tasks": summary["damaged_file_tasks"],
        "stray_file_tasks": summary["stray_file_tasks"],
        "leak_tasks": sum(1 for r in rows if r["leaked_markers"]),
        "extraction_without_prior_full_read": [v for r in rows for v in extraction_without_prior_full_read(r)],
        # reported
        "oracle_passed_solvable": sum(1 for r in solvable if r["oracle_passed"]),
        "edit_opportunity_solvable": sum(1 for r in solvable if progress[r["task"]]["edit_opportunity"]),
        "diagnose_attempts": len(pairs),
        "diagnose_refused": dict(collections.Counter(rec["refused"] for _, _, rec, _ in pairs if rec.get("refused") is not None)),
        "diagnose_executed": len(executed),
        "diagnose_successful": len(successful),
        "diagnose_failed_by_reason": dict(collections.Counter(no_span_reason(call) for _, _, _, call in failed)),
        "localized_hit_diagnoses": localized_hits,
        "localization_precision": (localized_hits / len(successful)) if successful else None,
        "extracted_span_lines": {"total": sum(spans), "mean": (sum(spans) / len(spans)) if spans else None, "max": max(spans) if spans else None},
        "hit_undetermined": sum(1 for _, _, rec, _ in executed if rec.get("snapshot_matches_seed") is False),
        "target_kinds": dict(collections.Counter(
            ("none" if rec.get("target") is None else "py_symbol" if rec["path"].endswith(".py") else "json_pointer" if rec["path"].endswith(".json") else "other")
            for _, _, rec, _ in executed)),
        "escalations": dict(collections.Counter(str(r["agent_escalation"]) for r in rows)),
        "insufficient_task_outcomes": {r["task"]: [r["lane_state"], r["agent_escalation"]] for r in insufficient},
        "rounds": summary["rounds"], "prompt_tokens": summary["prompt_tokens"],
        "per_task": {r["task"]: {"localized_hit": any(d.get("hits_defect_localized") for d in r["diagnoses"]),
                                 "oracle_passed": r["oracle_passed"],
                                 "diagnoses": [{k: d.get(k) for k in ("path", "target", "success", "refused", "pre_read", "seed_span", "localized",
                                                                      "hits_defect", "hits_defect_localized", "snapshot_matches_seed")} for d in r["diagnoses"]]}
                     for r in solvable},
    }


def verdict(control: dict[str, Any], drift: dict[str, Any], treatment: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "validity_complete_rows": all(a["rows"] == EXPECTED_ROWS for a in (control, drift, treatment)),
        "validity_same_harness_treatment_drift": len(treatment["harness_sha256"]) == 1 and treatment["harness_sha256"] == drift["harness_sha256"],
        "validity_same_model_digest": len(treatment["model_digest"]) == 1 and treatment["model_digest"] == drift["model_digest"] == control["model_digest"],
        "validity_no_invalid_rows": all(a["invalid_solvable_rows"] == 0 for a in (control, drift, treatment)),
        "validity_drift_within_1": abs(drift["tasks_with_localized_hit"] - control["tasks_with_localized_hit"]) <= DRIFT_TOLERANCE,
        "primary_localized_hits_ge_3": treatment["tasks_with_localized_hit"] >= PRIMARY_MIN_LOCALIZED_HITS,
        "guard_false_verified_eq_0": treatment["lane_false_verified"] == 0,
        "guard_insufficient_false_completion_eq_0": treatment["false_completion_on_insufficient_evidence"] == 0,
        "guard_damaged_le_control": treatment["damaged_file_tasks"] <= control["damaged_file_tasks"],
        "guard_stray_le_control": treatment["stray_file_tasks"] <= control["stray_file_tasks"],
        "guard_no_leaks": treatment["leak_tasks"] == 0,
        "guard_no_extraction_without_full_read": len(treatment["extraction_without_prior_full_read"]) == 0,
    }
    validity_ok = all(v for k, v in checks.items() if k.startswith("validity"))
    return {"checks": checks, "result": "PASS" if all(checks.values()) else ("INCONCLUSIVE" if not validity_ok else "FAIL"),
            "localized_hit_gain_vs_control": treatment["tasks_with_localized_hit"] - control["tasks_with_localized_hit"]}


def main() -> int:
    gate_sha = sha256(GATE)
    rows = load_rows()
    control = arm_fields(select(rows, "qwen_evidence", CONTROL_GATE_SHA))
    drift = arm_fields(select(rows, "qwen_evidence", gate_sha))
    treatment = arm_fields(select(rows, "qwen_extract", gate_sha))
    result = {
        "gate": {"path": GATE.relative_to(ROOT).as_posix(), "sha256": gate_sha, "control_gate_sha256": CONTROL_GATE_SHA},
        "scorer": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": sha256(Path(__file__).resolve())},
        "control": control, "drift": drift, "treatment": treatment, "verdict": verdict(control, drift, treatment),
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("gate", "scorer", "verdict")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
