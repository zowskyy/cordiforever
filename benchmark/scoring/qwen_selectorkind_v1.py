"""Scorer for gate qwen_selectorkind_v1 (benchmark/gates/qwen_selectorkind_v1.md).

Written and hash-logged in EXPERIMENT_LOG.md before any qwen_selectorkind_v1 run. Derived from the frozen qwen_localedit_v1 scorer text; that file is unchanged. Every gate clause maps to one computed
field; the verdict uses only those fields. Do not edit after results exist: a change is a new scorer file with its own
recorded hash.

Arms:
  control   = frozen `qwen_localedit` rows carrying the qwen_localedit_v1 gate sha256 (inferential for the one factor)
  drift     = `qwen_localedit` rerun rows carrying the qwen_selectorkind_v1 gate sha256 (validity only)
  treatment = `qwen_selectorkind` rows carrying the qwen_selectorkind_v1 gate sha256
  thresholds P1/P2 are fixed numbers from frozen `qwen_extract` (damaged 5 -> <= 2; hidden-test passes 3)

Pairing (no fallback): diagnose records <-> diagnose calls positionally (count, path, success checks); successful
read_file calls <-> read_views positionally (count, path checks). Any violation raises.

Usage:  .venv\\Scripts\\python.exe benchmark\\scoring\\qwen_selectorkind_v1.py
Writes: benchmark/results/qwen_selectorkind_v1_frozen.json
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmark import repo_task_eval as rte  # noqa: E402
from benchmark.repo_tasks import TASKS_BY_NAME  # noqa: E402
from core.path_candidates import normalize  # noqa: E402

GATE = ROOT / "benchmark" / "gates" / "qwen_selectorkind_v1.md"
CONTROL_GATE_SHA = "c75c5c30b4863cdab184b0468ceb34e602137c6e666be9dbdade08c7f93191cb"  # qwen_localedit_v1
RESULTS = ROOT / "benchmark" / "results" / "repo_task_eval.jsonl"
OUT = ROOT / "benchmark" / "results" / "qwen_selectorkind_v1_frozen.json"
PYTHON_SELECTOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
EXPECTED_ROWS = 20
P1_MAX_DAMAGED = 2
P2_MIN_ORACLE = 3
GUARD_MIN_LOCALIZED = 6
GUARD_MAX_STRAY = 0
DRIFT_TOLERANCE = 1
COHORT = ("mathlib_divide_zero", "config_database_host", "config_add_feature", "textkit_truncate_limit",
          "textkit_slug_punctuation", "inventory_total_value", "inventory_low_stock_equal", "inventory_find_missing")
EDIT_FAILURE_REASONS = {
    "unknown_target": "is not a function, class, method or assignment defined in",
    "replacement_missing_target": "replacement must define",
    "clobbers_existing": "also redefines",
    "invalid_python": "is not valid Python",
    "would_break_file": "would no longer",
    "json_pointer_unresolved": "is not a JSON pointer that resolves",
    "json_type_change": "refusing to replace it",
    "invalid_json_value": "replacement must be a JSON value",
    "unsupported_file_type": "edit supports only",
    "no_change": "nothing would change",
    "missing_file": "File does not exist",
    "empty_replacement": "replacement must be non-empty",
}
EXPECTED_CONTROL = {"damaged_file_tasks": 0, "edit_executed_cumulative": 2}  # frozen qwen_localedit values (drift anchors)
FUNNEL = ("diagnosis_resolved", "localized_hit", "edit_opportunity", "edit_executed", "gold_intact", "hidden_test_pass")


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


def edit_failure_reason(call: dict[str, Any]) -> str:
    head = call.get("result_head", "")
    matches = [key for key, text in EDIT_FAILURE_REASONS.items() if text in head]
    return matches[0] if len(matches) == 1 else "other"


def task_funnel(row: dict[str, Any]) -> dict[str, bool]:
    task = TASKS_BY_NAME[row["task"]]
    gold = {normalize(g) for g in task.gold_files}
    paired_diagnoses(row)  # enforce the pairing invariant for every scored row
    progress = rte.progress_metrics(row, task, rte.repo_files(rte.REPOS_DIR / task.repo))
    flags = {
        "diagnosis_resolved": any(d.get("refused") is None and d["success"] and d.get("target") is not None for d in row["diagnoses"]),
        "localized_hit": any(d.get("hits_defect_localized") for d in row["diagnoses"]),
        "edit_opportunity": bool(progress["edit_opportunity"]),
        "edit_executed": any(c["tool"] in rte._MUTATING and c["success"] and normalize(str(c["args"].get("path") or "")) in gold for c in row["calls"]),
        "gold_intact": not any(g in gold for g in list(row["damaged_files"]) + list(row["invalid_gold_files"])),
        "hidden_test_pass": bool(row["oracle_passed"]),
    }
    return flags


def funnel_counts(per_task: dict[str, dict[str, bool]]) -> dict[str, Any]:
    raw = {stage: sum(1 for f in per_task.values() if f[stage]) for stage in FUNNEL}
    cumulative = {}
    for i, stage in enumerate(FUNNEL):
        cumulative[stage] = sum(1 for f in per_task.values() if all(f[s] for s in FUNNEL[: i + 1]))
    return {"raw": raw, "cumulative_in_order": cumulative}


def selector_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Gate definition: kind = explicit selector_kind if present, else from the path extension; syntax validity per kind."""
    edits = [c for r in rows for c in r["calls"] if c["tool"] == "edit_symbol"]
    per_kind: dict[str, dict[str, int]] = {}
    explicit = matches = 0
    for call in edits:
        args = call["args"]
        path = str(args.get("path") or "")
        declared = args.get("selector_kind")
        ext_kind = "python_symbol" if path.endswith(".py") else "json_pointer" if path.endswith(".json") else "other"
        kind = str(declared) if declared is not None else ext_kind
        if declared is not None:
            explicit += 1
            matches += int(kind == ext_kind)
        target = args.get("target")
        target = target if isinstance(target, str) else ""
        valid = bool(PYTHON_SELECTOR.match(target)) if kind == "python_symbol" else target.startswith("/") if kind == "json_pointer" else False
        bucket = per_kind.setdefault(kind, {"attempted": 0, "syntax_valid": 0, "successful": 0})
        bucket["attempted"] += 1
        bucket["syntax_valid"] += int(valid)
        bucket["successful"] += int(bool(call["success"]))
    return {
        "edits_attempted": len(edits),
        "selector_syntax_valid": sum(b["syntax_valid"] for b in per_kind.values()),
        "per_kind": per_kind,
        "explicit_kind_calls": explicit,
        "kind_matches_file_type": matches,
    }


def arm_fields(by_task: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = list(by_task.values())
    solvable = [r for r in rows if r["expected_outcome"] == "verified_done"]
    insufficient = [r for r in rows if r["expected_outcome"] == "escalate"]
    summary = rte.summarize_condition(rows)
    per_task = {r["task"]: task_funnel(r) for r in solvable}
    successful_diag = [d for r in solvable for d in r["diagnoses"] if d.get("refused") is None and d["success"]]
    localized_hit_diagnoses = sum(1 for d in successful_diag if d.get("hits_defect_localized"))
    edit_calls = [c for r in rows for c in r["calls"] if c["tool"] == "edit_symbol"]
    return {
        # validity
        "rows": len(rows), "solvable_rows": len(solvable),
        "invalid_solvable_rows": sum(1 for r in solvable if r["truncated_read_views"] != 0),
        "harness_sha256": sorted({r["experiment"]["harness_sha256"] for r in rows}),
        "model_digest": sorted({r["experiment"]["model_digest"] for r in rows}),
        # primary
        "damaged_file_tasks": summary["damaged_file_tasks"],
        "oracle_passed_solvable": sum(1 for r in solvable if r["oracle_passed"]),
        # guardrails
        "tasks_with_localized_hit": sum(1 for r in solvable if any(d.get("hits_defect_localized") for d in r["diagnoses"])),
        "lane_false_verified": summary["lane_false_verified"],
        "false_completion_on_insufficient_evidence": sum(1 for r in insufficient if r["false_completion_on_insufficient_evidence"]),
        "stray_file_tasks": summary["stray_file_tasks"],
        "leak_tasks": sum(1 for r in rows if r["leaked_markers"]),
        "extraction_without_prior_full_read": [v for r in rows for v in extraction_without_prior_full_read(r)],
        # reported
        "funnel": funnel_counts(per_task),
        "per_task_funnel": per_task,
        "cohort_funnel": {t: per_task.get(t) for t in COHORT},
        "damaged_tasks": sorted(r["task"] for r in rows if r["damaged_files"]),
        "insufficient_tasks": {r["task"]: {"mutation_executed": any(c["tool"] in rte._MUTATING and c["success"] for c in r["calls"]),
                                           "damaged": bool(r["damaged_files"]), "lane_state": r["lane_state"]} for r in insufficient},
        "edit_calls": {"attempted": len(edit_calls), "successful": sum(1 for c in edit_calls if c["success"]),
                       "failed_by_reason": dict(collections.Counter(edit_failure_reason(c) for c in edit_calls if not c["success"]))},
        "guard_rejections_by_reason": dict(collections.Counter(g.get("reason") for r in rows for g in r["guard_rejections"])),
        "overwrite_existing_file_refusals": sum(1 for r in rows for g in r["guard_rejections"] if g.get("reason") == "overwrite_existing_file"),
        "failure_split": dict(collections.Counter(str(r["failure_split"]) for r in solvable if r["failure_split"])),
        "localization_precision": (localized_hit_diagnoses / len(successful_diag)) if successful_diag else None,
        "escalations": dict(collections.Counter(str(r["agent_escalation"]) for r in rows)),
        "selector": selector_metrics(rows),
        "rounds": summary["rounds"], "prompt_tokens": summary["prompt_tokens"],
    }


def verdict(control: dict[str, Any], drift: dict[str, Any], treatment: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "validity_complete_rows": all(a["rows"] == EXPECTED_ROWS for a in (control, drift, treatment)),
        "validity_same_harness_treatment_drift": len(treatment["harness_sha256"]) == 1 and treatment["harness_sha256"] == drift["harness_sha256"],
        "validity_same_model_digest": len(treatment["model_digest"]) == 1 and treatment["model_digest"] == drift["model_digest"] == control["model_digest"],
        "validity_no_invalid_rows": all(a["invalid_solvable_rows"] == 0 for a in (control, drift, treatment)),
        "validity_control_matches_frozen_values": control["damaged_file_tasks"] == EXPECTED_CONTROL["damaged_file_tasks"]
                                                  and control["funnel"]["cumulative_in_order"]["edit_executed"] == EXPECTED_CONTROL["edit_executed_cumulative"],
        "validity_drift_edit_executed_within_1": abs(drift["funnel"]["cumulative_in_order"]["edit_executed"] - control["funnel"]["cumulative_in_order"]["edit_executed"]) <= DRIFT_TOLERANCE,
        "validity_drift_damaged_within_1": abs(drift["damaged_file_tasks"] - control["damaged_file_tasks"]) <= DRIFT_TOLERANCE,
        "primary_p1_damaged_le_2": treatment["damaged_file_tasks"] <= P1_MAX_DAMAGED,
        "primary_p2_oracle_ge_3": treatment["oracle_passed_solvable"] >= P2_MIN_ORACLE,
        "guard_localized_hits_ge_6": treatment["tasks_with_localized_hit"] >= GUARD_MIN_LOCALIZED,
        "guard_false_verified_eq_0": treatment["lane_false_verified"] == 0,
        "guard_insufficient_false_completion_eq_0": treatment["false_completion_on_insufficient_evidence"] == 0,
        "guard_stray_le_0": treatment["stray_file_tasks"] <= GUARD_MAX_STRAY,
        "guard_no_leaks": treatment["leak_tasks"] == 0,
        "guard_no_extraction_without_full_read": len(treatment["extraction_without_prior_full_read"]) == 0,
    }
    validity_ok = all(v for k, v in checks.items() if k.startswith("validity"))
    return {"checks": checks, "result": "PASS" if all(checks.values()) else ("INCONCLUSIVE" if not validity_ok else "FAIL")}


def main() -> int:
    gate_sha = sha256(GATE)
    rows = load_rows()
    control = arm_fields(select(rows, "qwen_localedit", CONTROL_GATE_SHA))
    drift = arm_fields(select(rows, "qwen_localedit", gate_sha))
    treatment = arm_fields(select(rows, "qwen_selectorkind", gate_sha))
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
