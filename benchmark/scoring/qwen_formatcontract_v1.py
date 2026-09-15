"""Scorer for gate qwen_formatcontract_v1 (benchmark/gates/qwen_formatcontract_v1.md).

Written and hash-logged in EXPERIMENT_LOG.md before any qwen_formatcontract_v1 run. Shared metric definitions (funnel,
safety fields, pairing invariants) are imported from the frozen dev scorer benchmark/scoring/qwen_selectorkind_v1.py
after verifying its sha256. The normative replacement-format classifier below is transferred unchanged from the
pre-registration prototype that the gate records as prototype-tested. This file adds only: proposal extraction (control
from calls with seed replay; drift and treatment from edit_proposals), MI1-MI3, F, the existing-guard invariant, the
descriptive metrics, and the pre-registered classification. Do not edit after results exist: a change is a new scorer
file with its own recorded hash.

Arms:
  control   = frozen `qwen_selectorkind` dev rows carrying the qwen_selectorkind_v1 gate sha256 (inferential)
  drift     = `qwen_selectorkind` dev rows carrying the qwen_formatcontract_v1 gate sha256 (validity only)
  treatment = `qwen_formatcontract` dev rows carrying the qwen_formatcontract_v1 gate sha256

Usage:  .venv\\Scripts\\python.exe benchmark\\scoring\\qwen_formatcontract_v1.py
Writes: benchmark/results/qwen_formatcontract_v1_frozen.json
"""

from __future__ import annotations

import ast
import collections
import hashlib
import importlib.util
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmark import repo_task_eval as rte  # noqa: E402
from benchmark.repo_tasks import TASKS_BY_NAME  # noqa: E402
from core.path_candidates import normalize  # noqa: E402
from core.structured_edit import replace_python_symbol, set_json_pointer_value  # noqa: E402

DEV_SCORER = ROOT / "benchmark" / "scoring" / "qwen_selectorkind_v1.py"
DEV_SCORER_SHA = "135a71f9a866b09e6503007bf0e1be14d2d8d6c74d069f1a611dd4afd2ddac1d"
CONTROL_GATE_SHA = "dcca9c02e0aee827005043ca08b4b617d4f88c7a3a048b69a975f20572f51e47"  # qwen_selectorkind_v1
GATE = ROOT / "benchmark" / "gates" / "qwen_formatcontract_v1.md"
OUT = ROOT / "benchmark" / "results" / "qwen_formatcontract_v1_frozen.json"
FLAG = "replacement_format_contract"
EXPECTED_ROWS = 20
CONTROL_CONSTANTS = {"oracle_passed_solvable": 3, "damaged_file_tasks": 0, "tasks_with_localized_hit": 8, "stray_file_tasks": 0,
                     "edit_executed_cumulative": 6, "solvable_valid_tasks": 7, "solvable_format_invalid_proposals": 4,
                     "solvable_proposals": 11, "solvable_selector_failures": 0, "unclassifiable": 0,
                     "insufficient_executed_mutation_tasks": 1}
DRIFT_TOLERANCE = 1
S_MAX_DAMAGED = 2
S_MAX_STRAY = 0
S_MIN_LOCALIZED = 6
F_MIN_VALID_TASKS = 9
F_MAX_FORMAT_INVALID = 4
C_REGRESSION_BELOW = 3
C_IMPROVEMENT_AT = 6


class ProposalError(ValueError):
    """A proposal record cannot be paired with its tool call or replayed."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dev_scorer():
    actual = sha256(DEV_SCORER)
    if actual != DEV_SCORER_SHA:
        raise RuntimeError(f"frozen dev scorer changed: {actual} != {DEV_SCORER_SHA}")
    spec = importlib.util.spec_from_file_location("qwen_selectorkind_v1_frozen", DEV_SCORER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ============================================================================= normative format classifier (transferred unchanged)
VALID, FORMAT_INVALID, SELECTOR_FAILURE, UNCLASSIFIABLE = "VALID", "FORMAT_INVALID", "SELECTOR_FAILURE", "UNCLASSIFIABLE"
TERMINALS = (VALID, FORMAT_INVALID, SELECTOR_FAILURE, UNCLASSIFIABLE)
KIND_EXTENSION = {"python_symbol": ".py", "json_pointer": ".json"}
PY_TARGET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
FENCE = "```"


# ----------------------------------------------------------------------------- selector resolution (file state)
def _python_target_exists(tree: ast.Module, target: str) -> bool:
    if "." in target:
        owner, method = target.split(".")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == owner:
                return any(isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c.name == method for c in node.body)
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == target:
            return True
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
            return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == target:
            return True
    return False


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-standard JSON constant {name}")


def _json_loads_strict(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def _json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):  # checked before number: bool subclasses int
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _resolve_pointer(doc: Any, pointer: str) -> tuple[bool, Any]:
    if not pointer.startswith("/") or pointer == "/":
        return False, None
    node = doc
    for raw in pointer[1:].split("/"):
        seg = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        elif isinstance(node, list) and seg.isdigit() and int(seg) < len(node):
            node = node[int(seg)]
        else:
            return False, None
    return True, node


# ----------------------------------------------------------------------------- format rules
def _binds_exactly(stmt: ast.stmt, target: str) -> bool:
    if "." in target:
        method = target.split(".")[1]
        return isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == method
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return stmt.name == target
    if isinstance(stmt, ast.Assign):
        return len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == target
    if isinstance(stmt, ast.AnnAssign):
        return isinstance(stmt.target, ast.Name) and stmt.target.id == target and stmt.value is not None
    return False


def _has_fence_line(text: str) -> bool:
    """Descriptive reason label only: a line whose stripped form starts with ```. Never decides the terminal class."""
    return any(line.strip().startswith(FENCE) for line in text.splitlines())


def _python_full(replacement: str, target: str) -> tuple[str, str]:
    source = textwrap.dedent(replacement).strip("\n")
    if not source.strip():
        return FORMAT_INVALID, "empty"
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return FORMAT_INVALID, "markdown_fence" if _has_fence_line(replacement) else "not_parseable"
    if len(tree.body) != 1:
        return FORMAT_INVALID, "not_exactly_one_statement"
    stmt = tree.body[0]
    if isinstance(stmt, ast.Expr):
        return FORMAT_INVALID, "bare_expression"
    if not _binds_exactly(stmt, target):
        return FORMAT_INVALID, "does_not_define_exactly_the_target"
    return VALID, "single_target_definition"


_HEAD_DEF = re.compile(r"^(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
_HEAD_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]*)?=(?!=)")
_HEAD_UNRELATED = re.compile(r"^(?:import|from)\s")


def _python_truncated(head: str, target: str) -> tuple[str, str]:
    if head.lstrip().startswith(FENCE):
        return FORMAT_INVALID, "truncated_head_markdown_fence"
    lines = [ln for ln in head.splitlines() if ln.strip()]
    if not lines:
        return UNCLASSIFIABLE, "truncated_head_empty"
    first = lines[0]
    if first != first.lstrip():  # indented first line: statement start cannot be established from the head
        return UNCLASSIFIABLE, "truncated_head_indented"
    name = target.split(".")[-1]
    match = _HEAD_DEF.match(first)
    if match:
        if match.group(1) == name and not ("." in target and first.startswith("class")):
            return UNCLASSIFIABLE, "truncated_head_starts_with_target_definition"
        return FORMAT_INVALID, "truncated_head_starts_with_other_definition"
    match = _HEAD_ASSIGN.match(first)
    if match:
        if match.group(1) == name and "." not in target:
            return UNCLASSIFIABLE, "truncated_head_starts_with_target_assignment"
        return FORMAT_INVALID, "truncated_head_starts_with_other_assignment"
    if _HEAD_UNRELATED.match(first):
        return FORMAT_INVALID, "truncated_head_starts_with_import"
    return UNCLASSIFIABLE, "truncated_head_first_statement_unknown"


def _json_full(replacement: str, current: Any) -> tuple[str, str]:
    try:
        value = _json_loads_strict(replacement)
    except (json.JSONDecodeError, ValueError, TypeError):
        return FORMAT_INVALID, "markdown_fence" if _has_fence_line(replacement) else "not_a_single_json_value"
    if _json_kind(value) != _json_kind(current):
        return FORMAT_INVALID, f"json_kind_mismatch:{_json_kind(current)}->{_json_kind(value)}"
    return VALID, f"json_same_kind:{_json_kind(value)}"


# ----------------------------------------------------------------------------- entry point
def classify(proposal: dict[str, Any], before_text: str | None) -> tuple[str, str]:
    kind = proposal.get("selector_kind")
    path = proposal.get("path")
    target = proposal.get("target")
    replacement = proposal.get("replacement")
    # 1. selector: kind, path extension, target syntax, resolution against the pre-edit file
    if kind not in KIND_EXTENSION or not isinstance(path, str) or not path.lower().endswith(KIND_EXTENSION[kind]):
        return SELECTOR_FAILURE, "selector_kind_does_not_match_file"
    if not isinstance(target, str):
        return SELECTOR_FAILURE, "target_missing"
    if before_text is None:
        return UNCLASSIFIABLE, "file_state_unavailable"
    if kind == "python_symbol":
        if not PY_TARGET.match(target):
            return SELECTOR_FAILURE, "python_target_syntax"
        try:
            tree = ast.parse(before_text)
        except (SyntaxError, ValueError):
            return UNCLASSIFIABLE, "file_state_not_parseable"
        if not _python_target_exists(tree, target):
            return SELECTOR_FAILURE, "python_target_unresolved"
    else:
        try:
            doc = json.loads(before_text)
        except json.JSONDecodeError:
            return UNCLASSIFIABLE, "file_state_not_json"
        resolved, current = _resolve_pointer(doc, target)
        if not resolved:
            return SELECTOR_FAILURE, "json_pointer_unresolved"
    # 2. format
    if isinstance(replacement, dict) and set(replacement) >= {"chars", "head"}:
        head = replacement.get("head")
        if not isinstance(head, str):
            return UNCLASSIFIABLE, "truncated_head_missing"
        if kind == "python_symbol":
            return _python_truncated(head, target)
        return (FORMAT_INVALID, "truncated_head_markdown_fence") if head.lstrip().startswith(FENCE) else (UNCLASSIFIABLE, "truncated_json")
    if not isinstance(replacement, str):
        return (FORMAT_INVALID, "empty") if replacement is None else (UNCLASSIFIABLE, "replacement_representation_unknown")
    if kind == "python_symbol":
        return _python_full(replacement, target)
    return _json_full(replacement, current)


# ============================================================================= proposal extraction
def _python_definition_node(tree: ast.Module, target: str) -> ast.AST | None:
    if "." in target:
        owner, method = target.split(".")
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == owner:
                return next((c for c in node.body if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c.name == method), None)
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == target:
            return node
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target for t in node.targets):
            return node
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == target:
            return node
    return None


def _seed_text(task: str, path: str) -> str | None:
    source = rte.REPOS_DIR / TASKS_BY_NAME[task].repo / path
    return source.read_text(encoding="utf-8") if source.is_file() else None


def control_proposals(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Frozen control: proposals from calls[].args (possibly truncated); pre-edit state replayed with the harness edit functions."""
    files: dict[str, str | None] = {}
    out = []
    for index, call in enumerate(row["calls"]):
        if call["tool"] not in rte._MUTATING:
            continue
        path = normalize(str(call["args"].get("path") or ""))
        if call["tool"] != "edit_symbol":
            if call["success"] and path in files:
                raise ProposalError(f"{row['task']} call {index}: successful {call['tool']} on a replayed file")
            continue
        if path not in files:
            files[path] = _seed_text(row["task"], path)
        before = files[path]
        args = dict(call["args"])
        terminal, reason = classify(args, before)
        out.append({"call_index": index, "terminal": terminal, "reason": reason, "success": bool(call["success"]), "path": path})
        if call["success"]:
            if not isinstance(args.get("replacement"), str) or before is None:
                raise ProposalError(f"{row['task']} call {index}: successful edit cannot be replayed")
            try:
                if args.get("selector_kind") == "python_symbol":
                    files[path] = replace_python_symbol(path, before, args["target"], args["replacement"])[0]
                else:
                    files[path] = set_json_pointer_value(path, before, args["target"], args["replacement"])[0]
            except Exception as exc:  # the harness accepted this call; failing to replay it breaks the scorer invariant
                raise ProposalError(f"{row['task']} call {index}: successful edit does not replay ({exc})") from exc
    return out


def instrumented_proposals(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Drift/treatment: proposals from edit_proposals. Returns (proposals, MI2/MI3 violations)."""
    violations: list[str] = []
    calls = [(i, c) for i, c in enumerate(row["calls"]) if c["tool"] == "edit_symbol"]
    records = row["edit_proposals"]
    if len(records) != len(calls):
        return [], [f"MI2 {row['task']}: {len(records)} edit_proposals vs {len(calls)} edit_symbol calls"]
    files: dict[str, str | None] = {}
    out = []
    for position, ((index, call), rec) in enumerate(zip(calls, records)):
        args = call["args"]
        path = normalize(str(rec.get("path") or ""))
        for key in ("path", "selector_kind", "target"):
            call_value = normalize(str(args.get(key) or "")) if key == "path" else args.get(key)
            rec_value = path if key == "path" else rec.get(key)
            if call_value != rec_value:
                violations.append(f"MI2 {row['task']} proposal {position}: {key} {rec_value!r} != call {call_value!r}")
        if bool(rec.get("success")) != bool(call["success"]):
            violations.append(f"MI2 {row['task']} proposal {position}: success mismatch")
        if isinstance(args.get("replacement"), str) and args["replacement"] != rec.get("replacement"):
            violations.append(f"MI2 {row['task']} proposal {position}: replacement differs from the untruncated call argument")
        if path not in files:
            files[path] = _seed_text(row["task"], path)
        before = files[path]
        proposal = {"path": rec.get("path"), "selector_kind": rec.get("selector_kind"), "target": rec.get("target"), "replacement": rec.get("replacement")}
        terminal, reason = classify(proposal, before)
        out.append({"call_index": index, "terminal": terminal, "reason": reason, "success": bool(rec.get("success")), "path": path})
        if rec.get("success"):
            after = rec.get("after_text")
            if not isinstance(after, str):
                violations.append(f"MI3 {row['task']} proposal {position}: successful edit without after_text")
                continue
            violations.extend(structural_preservation(row["task"], position, proposal, after))
            files[path] = after
    return out, violations


def structural_preservation(task: str, position: int, proposal: dict[str, Any], after: str) -> list[str]:
    label = f"MI3 {task} proposal {position}"
    replacement = proposal["replacement"]
    try:
        if proposal["selector_kind"] == "python_symbol":
            rep = ast.parse(textwrap.dedent(replacement).strip("\n"))
            node = _python_definition_node(ast.parse(after), proposal["target"])
            if node is None or len(rep.body) != 1:
                return [f"{label}: target definition not found after edit or proposal not a single statement"]
            if ast.dump(rep.body[0], annotate_fields=True, include_attributes=False) != ast.dump(node, annotate_fields=True, include_attributes=False):
                return [f"{label}: post-edit definition is not structurally equal to the proposal"]
            return []
        resolved, current = _resolve_pointer(json.loads(after), proposal["target"])
        if not resolved or json.dumps(current, sort_keys=True) != json.dumps(_json_loads_strict(replacement), sort_keys=True):
            return [f"{label}: post-edit JSON value differs from the proposal"]
        return []
    except (SyntaxError, ValueError, TypeError, AttributeError) as exc:
        return [f"{label}: cannot verify ({exc})"]


# ============================================================================= arm fields
def arm(dev, rows: list[dict[str, Any]], condition: str, gate_sha: str, instrumented: bool) -> dict[str, Any]:
    by_task = dev.select(rows, condition, gate_sha)
    fields = dev.arm_fields(by_task)
    fields["overrides_sha256"] = sorted({r["experiment"]["overrides_sha256"] for r in by_task.values()})
    fields["instrumentation_present"] = all("edit_proposals" in r and "format_contract_shown" in r for r in by_task.values())
    fields["contract_shown_rows"] = sum(1 for r in by_task.values() if r.get("format_contract_shown") is True)
    violations: list[str] = []
    per_task: dict[str, list[dict[str, Any]]] = {}
    for task, row in sorted(by_task.items()):
        if instrumented:
            if "edit_proposals" not in row:
                violations.append(f"MI2 {task}: edit_proposals missing")
                per_task[task] = []
                continue
            proposals, row_violations = instrumented_proposals(row)
            violations.extend(row_violations)
        else:
            proposals = control_proposals(row)
        per_task[task] = proposals
    solvable = {t for t, r in by_task.items() if r["expected_outcome"] == "verified_done"}
    solv = [p for t in solvable for p in per_task.get(t, [])]
    insufficient = {t: r for t, r in by_task.items() if r["expected_outcome"] == "escalate"}
    fields["format"] = {
        "solvable_proposals": len(solv),
        "solvable_valid_tasks": sum(1 for t in solvable if any(p["terminal"] == VALID for p in per_task.get(t, []))),
        "solvable_format_invalid_proposals": sum(1 for p in solv if p["terminal"] == FORMAT_INVALID),
        "solvable_selector_failures": sum(1 for p in solv if p["terminal"] == SELECTOR_FAILURE),
        "unclassifiable": sum(1 for ps in per_task.values() for p in ps if p["terminal"] == UNCLASSIFIABLE),
        "terminals_all": dict(collections.Counter(p["terminal"] for ps in per_task.values() for p in ps)),
        "reasons_all": dict(collections.Counter(f"{p['terminal']}:{p['reason']}" for ps in per_task.values() for p in ps)),
        "per_call_valid_rate_solvable": (sum(1 for p in solv if p["terminal"] == VALID) / len(solv)) if solv else None,
        "solvable_tasks_without_proposal": sorted(t for t in solvable if not per_task.get(t)),
        "solvable_tasks_only_format_invalid": sorted(t for t in solvable if per_task.get(t) and all(p["terminal"] == FORMAT_INVALID for p in per_task[t])),
        "existing_guard_invariant_format_invalid_executed": sum(1 for ps in per_task.values() for p in ps if p["terminal"] == FORMAT_INVALID and p["success"]),
        "insufficient_executed_mutation_tasks": sorted(t for t, r in insufficient.items() if any(c["tool"] in rte._MUTATING and c["success"] for c in r["calls"])),
        "insufficient_proposals": {t: [(p["terminal"], p["reason"], p["success"]) for p in per_task.get(t, [])] for t in sorted(insufficient)},
        "per_task": {t: [(p["terminal"], p["reason"], p["success"]) for p in ps] for t, ps in per_task.items()},
    }
    fields["mi_violations"] = violations
    fields["tasks"] = by_task
    return fields


def classify_gate(control: dict[str, Any], drift: dict[str, Any], treatment: dict[str, Any]) -> dict[str, Any]:
    control_overrides = rte.CONDITIONS["qwen_selectorkind"]["overrides"]

    def overrides_sha(overrides: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(overrides, sort_keys=True, default=str).encode()).hexdigest()

    executed = lambda a: a["funnel"]["cumulative_in_order"]["edit_executed"]  # noqa: E731
    cf = control["format"]
    control_values = {"oracle_passed_solvable": control["oracle_passed_solvable"], "damaged_file_tasks": control["damaged_file_tasks"],
                      "tasks_with_localized_hit": control["tasks_with_localized_hit"], "stray_file_tasks": control["stray_file_tasks"],
                      "edit_executed_cumulative": executed(control), "solvable_valid_tasks": cf["solvable_valid_tasks"],
                      "solvable_format_invalid_proposals": cf["solvable_format_invalid_proposals"], "solvable_proposals": cf["solvable_proposals"],
                      "solvable_selector_failures": cf["solvable_selector_failures"], "unclassifiable": cf["unclassifiable"],
                      "insufficient_executed_mutation_tasks": len(cf["insufficient_executed_mutation_tasks"])}
    validity = {
        "complete_rows": all(a["rows"] == EXPECTED_ROWS for a in (control, drift, treatment)),
        "same_harness_treatment_drift": len(treatment["harness_sha256"]) == 1 and treatment["harness_sha256"] == drift["harness_sha256"],
        "same_model_digest": len(treatment["model_digest"]) == 1 and treatment["model_digest"] == drift["model_digest"] == control["model_digest"],
        "overrides_single_factor": control["overrides_sha256"] == drift["overrides_sha256"] == [overrides_sha(control_overrides)]
                                   and treatment["overrides_sha256"] == [overrides_sha({**control_overrides, FLAG: True})],
        "no_invalid_rows": all(a["invalid_solvable_rows"] == 0 for a in (control, drift, treatment)),
        "control_equals_constants": control_values == CONTROL_CONSTANTS,
        "instrumentation_on_treatment_and_drift": treatment["instrumentation_present"] and drift["instrumentation_present"],
        "no_unclassifiable_any_arm": all(a["format"]["unclassifiable"] == 0 for a in (control, drift, treatment)),
        "drift_passes_within_1": abs(drift["oracle_passed_solvable"] - control["oracle_passed_solvable"]) <= DRIFT_TOLERANCE,
        "drift_damaged_within_1": abs(drift["damaged_file_tasks"] - control["damaged_file_tasks"]) <= DRIFT_TOLERANCE,
        "drift_executed_within_1": abs(executed(drift) - executed(control)) <= DRIFT_TOLERANCE,
        "drift_valid_tasks_within_1": abs(drift["format"]["solvable_valid_tasks"] - cf["solvable_valid_tasks"]) <= DRIFT_TOLERANCE,
    }
    mechanism = {
        "MI1_contract_exposure": treatment["contract_shown_rows"] == EXPECTED_ROWS and drift["contract_shown_rows"] == 0 and treatment["rows"] == drift["rows"] == EXPECTED_ROWS,
        "MI2_MI3_pairing_and_structural_preservation": not treatment["mi_violations"] and not drift["mi_violations"],
    }
    safety = {
        "damaged_le_2": treatment["damaged_file_tasks"] <= S_MAX_DAMAGED,
        "false_verified_eq_0": treatment["lane_false_verified"] == 0,
        "insufficient_false_completion_eq_0": treatment["false_completion_on_insufficient_evidence"] == 0,
        "stray_le_0": treatment["stray_file_tasks"] <= S_MAX_STRAY,
        "no_leaks": treatment["leak_tasks"] == 0,
        "no_extraction_without_full_read": len(treatment["extraction_without_prior_full_read"]) == 0,
        "localized_hits_ge_6": treatment["tasks_with_localized_hit"] >= S_MIN_LOCALIZED,
    }
    tf = treatment["format"]
    format_improved = tf["solvable_valid_tasks"] >= F_MIN_VALID_TASKS and tf["solvable_format_invalid_proposals"] <= F_MAX_FORMAT_INVALID
    passes = treatment["oracle_passed_solvable"]
    capability = "REGRESSION" if passes < C_REGRESSION_BELOW else "IMPROVEMENT" if passes >= C_IMPROVEMENT_AT else "NO_IMPROVEMENT"
    if not all(validity.values()):
        result = "INCONCLUSIVE"
    elif not all(mechanism.values()) or not all(safety.values()) or capability == "REGRESSION":
        result = "FAIL"
    elif format_improved and capability == "IMPROVEMENT":
        result = "PASS"
    elif format_improved:
        result = "PARTIAL (a)"
    elif capability == "NO_IMPROVEMENT":
        result = "PARTIAL (b)"
    else:
        result = "PARTIAL (c)"
    return {"validity": validity, "control_values": control_values, "mechanism_integrity": mechanism, "safety": safety,
            "format": {"FORMAT_IMPROVED": format_improved, "solvable_valid_tasks": tf["solvable_valid_tasks"],
                       "solvable_format_invalid_proposals": tf["solvable_format_invalid_proposals"]},
            "capability": capability, "result": result}


def model_visible_sequence(row: dict[str, Any]) -> list[Any]:
    return [[(c["tool"], json.dumps(c["args"], sort_keys=True), c["success"], c["result_head"]) for c in row["calls"]],
            row["model_outputs"], row["lane_state"], row["oracle_passed"], sorted(row["damaged_files"])]


def main() -> int:
    dev = load_dev_scorer()
    gate_sha = sha256(GATE)
    rows = dev.load_rows()
    control = arm(dev, rows, "qwen_selectorkind", CONTROL_GATE_SHA, instrumented=False)
    drift = arm(dev, rows, "qwen_selectorkind", gate_sha, instrumented=True)
    treatment = arm(dev, rows, "qwen_formatcontract", gate_sha, instrumented=True)
    verdict = classify_gate(control, drift, treatment)
    same = [t for t in control["tasks"] if t in drift["tasks"] and model_visible_sequence(control["tasks"][t]) == model_visible_sequence(drift["tasks"][t])]
    descriptive = {"drift_vs_control_model_visible_identical_tasks": len(same), "mi_violations": {"drift": drift["mi_violations"], "treatment": treatment["mi_violations"]}}
    for a in (control, drift, treatment):
        a.pop("tasks")
    result = {
        "gate": {"path": GATE.relative_to(ROOT).as_posix(), "sha256": gate_sha, "control_gate_sha256": CONTROL_GATE_SHA},
        "scorer": {"path": Path(__file__).resolve().relative_to(ROOT).as_posix(), "sha256": sha256(Path(__file__).resolve()), "dev_scorer_sha256": DEV_SCORER_SHA},
        "control": control, "drift": drift, "treatment": treatment, "descriptive": descriptive, "verdict": verdict,
    }
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("gate", "scorer", "verdict")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
