"""Furthest-Reached Bottleneck Taxonomy (benchmark/analysis/furthest_bottleneck_taxonomy.md).

Deterministic fact extraction and classification over frozen trajectory rows. Descriptive analysis methodology, not an
experiment scorer. Invariant: UNKNOWN is not FALSE; every stage fact is tri-state and unestablished evidence stays
UNKNOWN. Oracle replay uses the existing independent `run_oracle` on temporary workspaces only.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[2]
FORMAT_SCORER = ROOT / "benchmark" / "scoring" / "qwen_formatcontract_v1.py"
FORMAT_SCORER_SHA = "7141c97c8377e73f3945646f2db54da71ada1708d223dd5174681e0b724d3413"
SELECTOR_SCORER = ROOT / "benchmark" / "scoring" / "qwen_selectorkind_v1.py"
SELECTOR_SCORER_SHA = "135a71f9a866b09e6503007bf0e1be14d2d8d6c74d069f1a611dd4afd2ddac1d"
MAX_ROUNDS = 12
MUTATING = ("write_file", "replace_text", "patch_json", "edit_symbol", "delete_file")
NON_PRIMITIVE = ("write_file", "replace_text", "patch_json", "delete_file")
STRUCTURAL_NOOP_TEXT = "structurally equivalent to the current definition"
PRECONDITION_TEXTS = ("has not been read", "send diagnose", "already exists")
BLOCKED_TEXTS = ("blocked after repeated failures", "Duplicate failed call", "already succeeded")
# F5 guard judgements describe the refused proposal's counterfactual; they do not judge whether the guard policy is correct.
GUARD_A = "A_protective_against_proposal"
GUARD_B = "B_counterfactually_successful_if_applied"
GUARD_C = "C_undetermined"


class Tri(Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


T, F, U = Tri.TRUE, Tri.FALSE, Tri.UNKNOWN


def tri(value: Any) -> Tri:
    """Only the literal booleans True/False are known; everything else (None, missing, 0, '', objects) is UNKNOWN."""
    if value is True:
        return T
    if value is False:
        return F
    return U


def tri_and(*values: Tri) -> Tri:
    if any(v is F for v in values):
        return F
    if any(v is U for v in values):
        return U
    return T


def tri_any(values: Iterable[Tri]) -> Tri:
    seen_unknown = False
    for v in values:
        if v is T:
            return T
        if v is U:
            seen_unknown = True
    return U if seen_unknown else F


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_frozen(path: Path, sha: str, name: str):
    actual = _sha256(path)
    if actual != sha:
        raise RuntimeError(f"frozen module changed: {path} {actual} != {sha}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FROZEN: dict[str, Any] = {}


def frozen_format_classifier():
    if "format" not in _FROZEN:
        _FROZEN["format"] = _load_frozen(FORMAT_SCORER, FORMAT_SCORER_SHA, "qwen_formatcontract_v1_frozen_taxonomy")
    return _FROZEN["format"]


def frozen_edit_failure_reasons() -> dict[str, str]:
    if "selector" not in _FROZEN:
        _FROZEN["selector"] = _load_frozen(SELECTOR_SCORER, SELECTOR_SCORER_SHA, "qwen_selectorkind_v1_frozen_taxonomy")
    return _FROZEN["selector"].EDIT_FAILURE_REASONS


# ============================================================================= data model
@dataclass
class ProposalFacts:
    index: int
    path: str
    target: Any
    relevant: Tri      # D7
    resolves: Tri      # D8
    valid: Tri         # D9
    accepted: Tri      # D10
    result_head: str = ""
    guard_reason: str | None = None
    guard_judgement: str | None = None  # A / B / C (descriptive)

    def chain(self, stage: int) -> Tri:
        parts = [self.relevant, self.resolves, self.valid, self.accepted][: stage - 6]
        return tri_and(*parts)

    def stop_stage(self) -> str:
        if self.relevant is not T:
            return "wrong_target" if self.relevant is F else "unknown_relevance"
        for label, value in (("F3_selector", self.resolves), ("F4_format", self.valid), ("F5_guard", self.accepted)):
            if value is F:
                return label
            if value is U:
                return f"unknown_before_{label}"
        return "accepted"


@dataclass
class TrajectoryFacts:
    defect_known: Tri                      # D1 and D2
    evidence: Tri                          # D3
    usable_diagnosis: Tri                  # D4
    localized: Tri                         # D5
    d0_harness: Tri = U                    # D0_HARNESS (normative applicability); UNKNOWN unless established
    d0_contract: Tri = U                   # D0_CONTRACT (descriptive only; never used by classify)
    diagnosis_attempted: Tri = U           # descriptive F1 sub-label input
    proposals: list[ProposalFacts] = field(default_factory=list)
    gold_edit_proposal_exists: bool = False
    non_primitive_attempts: list[str] = field(default_factory=list)
    state_correct: list[Tri] = field(default_factory=list)  # D11 per successful mutation state
    final_correct: Tri = U                                   # D11 at the final state
    regression_evidence: Tri = F                             # D12
    agent_escalation: Any = None
    model_claimed_done: Any = None
    rounds: Any = None
    f6_subtype: str | None = None


@dataclass
class BottleneckResult:
    label: str
    sub_label: str | None
    history: list[str]
    reach: dict[str, str]
    guard: list[tuple[str | None, str | None]] = field(default_factory=list)
    f6_subtype: str | None = None
    d0_harness: str = "UNKNOWN"
    d0_contract: str = "UNKNOWN"


# ============================================================================= classification (pure)
def classify(facts: TrajectoryFacts) -> BottleneckResult:
    history = [f"proposal{p.index}:{p.stop_stage()}" for p in facts.proposals] + [f"non_primitive:{op}" for op in facts.non_primitive_attempts]
    reach = {f"R{s}": tri_any(p.chain(s) for p in facts.proposals) for s in (7, 8, 9, 10)}
    shown = {k: v.value for k, v in reach.items()}

    def result(label: str, sub: str | None = None, **extra: Any) -> BottleneckResult:
        return BottleneckResult(label, sub, history, shown, d0_harness=facts.d0_harness.value, d0_contract=facts.d0_contract.value, **extra)

    # D0_HARNESS is the only applicability fact that affects the label; D0_CONTRACT is descriptive.
    if facts.d0_harness is F:
        return result("INTERFACE_UNSUPPORTED", "required_structural_operation_not_representable_by_enabled_interface")
    if facts.d0_harness is U:
        return result("UNDETERMINED", "action_space_applicability_unknown")
    if facts.defect_known is not T:
        return result("UNDETERMINED", "defect_region_or_relevant_target_unknown")
    r7, r8, r9, r10 = reach["R7"], reach["R8"], reach["R9"], reach["R10"]
    if r10 is T:
        any_correct = tri_any(facts.state_correct)
        if any_correct is T:
            if facts.final_correct is T:
                return result("F8", "final_state_passes_but_row_failed")
            if facts.final_correct is U:
                return result("UNDETERMINED", "final_state_correctness_unknown")
            if facts.regression_evidence is T:
                return result("F7", "correct_state_later_regressed")
            return result("UNDETERMINED", "correct_state_without_positive_regression_evidence")
        if any_correct is U:
            return result("UNDETERMINED", "accepted_state_correctness_unknown")
        return result("F6", "replacement_content", f6_subtype=facts.f6_subtype)
    if r10 is U:
        return result("UNDETERMINED", "acceptance_unknown")
    if r9 is T:
        guards = [(p.guard_reason, p.guard_judgement) for p in facts.proposals if p.chain(9) is T and p.accepted is F]
        return result("F5", guards[-1][0] if guards else None, guard=guards)
    if r9 is U:
        return result("UNDETERMINED", "structural_validity_unknown")
    if r8 is T:
        return result("F4", "no_structurally_valid_relevant_proposal")
    if r8 is U:
        return result("UNDETERMINED", "selector_resolution_unknown")
    if r7 is T:
        return result("F3", "relevant_selector_never_resolved")
    if r7 is U:
        return result("UNDETERMINED", "relevance_unknown")
    # No relevant proposal is known to exist.
    if facts.localized is T:
        if facts.gold_edit_proposal_exists:
            return result("F1", "edit_targets_wrong_location")
        return result("F2", _f2_sub_label(facts))
    if facts.localized is U:
        return result("UNDETERMINED", "localization_unknown")
    if facts.gold_edit_proposal_exists:
        return result("F1", "edit_targets_wrong_location")
    if facts.usable_diagnosis is T:
        return result("F1", "diagnosis_misses_defect")
    if facts.usable_diagnosis is U:
        return result("UNDETERMINED", "usable_diagnosis_unknown")
    if facts.evidence is F:
        return result("F0", "evidence_not_acquired")
    if facts.evidence is T:
        sub = {T: "diagnosis_attempted_unusable", F: "no_diagnosis_attempted"}.get(facts.diagnosis_attempted, "diagnosis_attempt_unknown")
        return result("F1", sub)
    return result("UNDETERMINED", "evidence_unknown")


def _f2_sub_label(facts: TrajectoryFacts) -> str:
    if facts.non_primitive_attempts and not facts.proposals:
        return "non_primitive_mutation_attempt_only:" + ",".join(facts.non_primitive_attempts)
    if facts.agent_escalation:
        return f"escalation:{facts.agent_escalation}"
    if facts.model_claimed_done is True:
        return "premature_done"
    if isinstance(facts.rounds, int) and facts.rounds >= MAX_ROUNDS:
        return "stall_or_max_rounds"
    return "other"


# ============================================================================= D1 / D2 / D7
def python_symbol_spans(text: str) -> dict[str, tuple[int, int]] | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        end = getattr(node, "end_lineno", None) or node.lineno
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            spans[node.name] = (start, end)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        cstart = min([child.lineno] + [d.lineno for d in child.decorator_list])
                        spans[f"{node.name}.{child.name}"] = (cstart, child.end_lineno or child.lineno)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    spans[t.id] = (node.lineno, end)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            spans[node.target.id] = (node.lineno, end)
    return spans


def widened_defect_region(seed_text: str, reference_text: str, defect_lines: Callable[[str, str], set[int]]) -> set[int]:
    return {n + d for n in defect_lines(seed_text, reference_text) for d in (-1, 0, 1)}


def relevant_python_symbols(seed_text: str, region: set[int]) -> set[str] | None:
    spans = python_symbol_spans(seed_text)
    if spans is None or not region:
        return None
    names = {name for name, (a, b) in spans.items() if set(range(a, b + 1)) & region}
    return names or None


def _pointer_segments(pointer: str) -> list[str]:
    return [s.replace("~1", "/").replace("~0", "~") for s in pointer[1:].split("/")]


def json_changed_locations(seed: Any, reference: Any, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    if isinstance(seed, dict) and isinstance(reference, dict):
        out: list[tuple[str, ...]] = []
        for key in sorted(set(seed) | set(reference)):
            if key not in seed or key not in reference:
                out.append(prefix + (key,))
            else:
                out.extend(json_changed_locations(seed[key], reference[key], prefix + (key,)))
        return out
    if isinstance(seed, list) and isinstance(reference, list):
        if len(seed) != len(reference):
            return [prefix]
        out = []
        for i, (a, b) in enumerate(zip(seed, reference)):
            out.extend(json_changed_locations(a, b, prefix + (str(i),)))
        return out
    if type(seed) is not type(reference) or seed != reference:
        return [prefix]
    return []


def normalize_python_target(target: str) -> str:
    text = target.strip()
    if text.startswith("/"):
        text = text[1:]
    for prefix in ("async def ", "def ", "class "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.split("(", 1)[0].strip()


def python_relevance(target: Any, relevant: set[str] | None) -> Tri:
    if relevant is None or not isinstance(target, str):
        return U
    name = normalize_python_target(target)
    if not name:
        return F
    if name in relevant or name.split(".")[-1] in {r.split(".")[-1] for r in relevant}:
        return T
    return F


def json_relevance(target: Any, changed: list[tuple[str, ...]] | None) -> Tri:
    if not changed or not isinstance(target, str):
        return U
    if target in ("", "/") or not target.startswith("/"):
        return F
    t = tuple(_pointer_segments(target))
    for c in changed:
        if t == c or (len(t) > len(c) and t[: len(c)] == c) or (len(c) == len(t) + 1 and c[: len(t)] == t):
            return T
    return F


def reference_added_python_names(seed_text: str, reference_text: str) -> set[str]:
    """D7 amendment: names defined in the reference but not in the seed count as relevant intent."""
    seed_spans, ref_spans = python_symbol_spans(seed_text), python_symbol_spans(reference_text)
    if seed_spans is None or ref_spans is None:
        return set()
    return set(ref_spans) - set(seed_spans)


# ============================================================================= D0 action-space applicability
def action_capabilities(overrides: dict[str, Any] | None) -> dict[str, bool] | None:
    """Mutating operations actually enabled by a condition's overrides (never inferred from model behavior)."""
    if not isinstance(overrides, dict):
        return None
    localized = overrides.get("localized_edits") is True
    return {
        "edit_symbol": localized,
        "replace_text": overrides.get("structured_edits") is True,
        "overwrite_existing": not localized,  # with localized_edits the loop refuses write_file on existing files
        "create_file": True,
    }


def _selectable(node: ast.stmt) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.AnnAssign)):
        return not isinstance(node, ast.AnnAssign) or isinstance(node.target, ast.Name)
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) for t in node.targets)


def _stmt_spans(tree: ast.Module) -> list[tuple[int, int, ast.stmt]]:
    out = []
    for node in tree.body:
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        out.append((start, node.end_lineno or node.lineno, node))
    return out


def d0_python_file(seed_text: str, reference_text: str, caps: dict[str, bool], sole_gold: bool) -> tuple[Tri, Tri, list[str]]:
    """Required structural operation classes for a .py gold file. Returns (D0_HARNESS, D0_CONTRACT, operation classes).

    Conservative necessity: a reference change to a non-selectable statement, or removal of a selectable name, is
    UNKNOWN (an alternative valid repair may not need it) unless the file has no selectable statement at all and is the
    task's sole gold file, in which case no enabled operation can change it (FALSE)."""
    import difflib

    if caps.get("overwrite_existing") or caps.get("replace_text"):
        return T, T, ["arbitrary_text_change"]
    try:
        seed_tree, ref_tree = ast.parse(seed_text), ast.parse(reference_text)
    except (SyntaxError, ValueError):
        return U, U, ["unparseable"]
    if not caps.get("edit_symbol"):
        return (F if sole_gold else U), (F if sole_gold else U), ["no_enabled_operation_for_existing_file"]
    spans = _stmt_spans(seed_tree)
    seed_lines, ref_lines = seed_text.splitlines(), reference_text.splitlines()
    any_selectable = any(_selectable(n) for _, _, n in spans)
    classes: list[str] = []
    harness, contract = T, T

    def containing(line: int) -> ast.stmt | None:
        return next((n for a, b, n in spans if a <= line <= b), None)

    def neutral(line: int) -> bool:
        text = seed_lines[line - 1] if 1 <= line <= len(seed_lines) else ""
        return not text.strip() or text.strip().startswith("#")

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=seed_lines, b=ref_lines, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            for line in range(i1 + 1, i2 + 1):
                node = containing(line)
                if node is None:
                    if neutral(line):
                        continue
                    classes.append("modify_unattributed_line")
                    harness, contract = tri_and(harness, U), tri_and(contract, U)
                elif _selectable(node):
                    classes.append("modify_selectable")
                else:
                    classes.append("modify_non_selectable")
                    verdict = F if (sole_gold and not any_selectable) else U
                    harness, contract = tri_and(harness, verdict), tri_and(contract, verdict)
        if tag in ("insert", "replace") and j2 > j1:
            inside = containing(i1) if tag == "insert" else None
            if tag == "insert" and inside is not None and containing(i1 + 1) is inside:
                if _selectable(inside):
                    classes.append("modify_selectable")
                else:
                    classes.append("modify_non_selectable")
                    verdict = F if (sole_gold and not any_selectable) else U
                    harness, contract = tri_and(harness, verdict), tri_and(contract, verdict)
                continue
            if tag == "replace":
                continue  # replaced lines were already attributed to their containing statements
            inserted = "\n".join(ref_lines[j1:j2])
            try:
                inserted_nodes = ast.parse(textwrap.dedent(inserted)).body
            except (SyntaxError, ValueError):
                inserted_nodes = None
            adjacent = False
            for a, b, n in spans:
                gap_after = range(b + 1, i1 + 1)
                gap_before = range(i1 + 1, a)
                if _selectable(n) and ((b <= i1 and all(neutral(x) for x in gap_after)) or (a >= i1 + 1 and all(neutral(x) for x in gap_before))):
                    adjacent = True
                    break
            if inserted_nodes is None:
                classes.append("insert_unparseable_fragment")
                harness, contract = tri_and(harness, U), tri_and(contract, U)
            elif not inserted_nodes:
                continue
            elif adjacent:
                classes.append("insert_top_level_statement_adjacent_to_selectable")
                contract = tri_and(contract, F)  # the single-definition contract cannot add a new top-level statement
            else:
                classes.append("insert_top_level_statement_without_selectable_anchor")
                verdict = F if (sole_gold and not any_selectable) else U
                harness, contract = tri_and(harness, verdict), tri_and(contract, verdict)
    seed_names = {n for n in (python_symbol_spans(seed_text) or {}) if "." not in n}
    ref_names = {n for n in (python_symbol_spans(reference_text) or {}) if "." not in n}
    if seed_names - ref_names:
        classes.append("remove_selectable_name")
        harness, contract = tri_and(harness, U), tri_and(contract, U)
    return harness, contract, classes


def d0_json_file(seed_text: str, reference_text: str, caps: dict[str, bool], sole_gold: bool) -> tuple[Tri, Tri, list[str]]:
    if caps.get("overwrite_existing") or caps.get("replace_text"):
        return T, T, ["arbitrary_text_change"]
    try:
        seed_doc, ref_doc = json.loads(seed_text), json.loads(reference_text)
    except ValueError:
        return U, U, ["unparseable"]
    if not caps.get("edit_symbol"):
        return (F if sole_gold else U), (F if sole_gold else U), ["no_enabled_operation_for_existing_file"]
    verdict, classes = T, []
    for loc in json_changed_locations(seed_doc, ref_doc):
        if loc == ():
            classes.append("replace_document_root")
            verdict = tri_and(verdict, F if sole_gold else U)
            continue
        ok = False
        for candidate in (loc, loc[:-1]):
            if candidate == ():
                continue
            s_node, r_node, resolved = seed_doc, ref_doc, True
            for seg in candidate:
                if isinstance(s_node, dict) and seg in s_node and isinstance(r_node, dict) and seg in r_node:
                    s_node, r_node = s_node[seg], r_node[seg]
                elif isinstance(s_node, list) and isinstance(r_node, list) and seg.isdigit() and int(seg) < min(len(s_node), len(r_node)):
                    s_node, r_node = s_node[int(seg)], r_node[int(seg)]
                else:
                    resolved = False
                    break
            if resolved and _json_kind_name(s_node) == _json_kind_name(r_node):
                ok = True
                break
        classes.append("set_resolvable_same_kind_value" if ok else "change_requires_unresolvable_or_kind_changing_set")
        if not ok:
            verdict = tri_and(verdict, U)
    return verdict, verdict, classes  # a JSON value set is already a single-value replacement


def _json_kind_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "string", list: "array", dict: "object"}.get(type(value), "other")


def d0_task(task: Any, caps: dict[str, bool] | None, repos_dir: Path, normalize: Callable[[str], str]) -> tuple[Tri, Tri, dict[str, list[str]]]:
    """D0_HARNESS (normative) and D0_CONTRACT (descriptive) over the task's gold files, from seed + reference + capabilities."""
    if caps is None or not task.reference_patch:
        return U, U, {}
    gold = [normalize(g) for g in task.gold_files]
    reference = {normalize(k): v for k, v in task.reference_patch.items()}
    harness, contract, detail = T, T, {}
    sole = len(gold) == 1
    for g in gold:
        seed_path = repos_dir / task.repo / g
        if g not in reference:
            harness, contract = tri_and(harness, U), tri_and(contract, U)
            detail[g] = ["no_reference_entry"]
            continue
        if not seed_path.is_file():
            ok = T if caps.get("create_file") else (F if sole else U)
            harness, contract = tri_and(harness, ok), tri_and(contract, ok)
            detail[g] = ["create_file"]
            continue
        seed_text = seed_path.read_text(encoding="utf-8")
        if seed_text == reference[g]:
            detail[g] = ["unchanged"]
            continue
        if g.endswith(".py"):
            h, c, classes = d0_python_file(seed_text, reference[g], caps, sole)
        elif g.endswith(".json"):
            h, c, classes = d0_json_file(seed_text, reference[g], caps, sole)
        else:
            both = T if (caps.get("overwrite_existing") or caps.get("replace_text")) else (F if sole else U)
            h, c, classes = both, both, ["non_code_text_change"]
        harness, contract = tri_and(harness, h), tri_and(contract, c)
        detail[g] = classes
    return harness, contract, detail


# ============================================================================= oracle replay
class OracleReplayer:
    """Runs the existing independent oracle on a temporary copy of the seed repo with file states applied."""

    def __init__(self, run_oracle: Callable[..., dict[str, Any]] | None = None, seed_workspace: Callable[..., Path] | None = None):
        self._run_oracle = run_oracle
        self._seed_workspace = seed_workspace
        self._cache: dict[str, tuple[Tri, str]] = {}

    def run(self, task: Any, files: dict[str, str | None]) -> tuple[Tri, str]:
        key = hashlib.sha256(json.dumps([task.name, sorted(files.items())], default=str).encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        try:
            if self._run_oracle is None or self._seed_workspace is None:
                from benchmark import repo_task_eval as rte
                run_oracle, seed_workspace = self._run_oracle or rte.run_oracle, self._seed_workspace or rte.seed_workspace
            else:
                run_oracle, seed_workspace = self._run_oracle, self._seed_workspace
            with tempfile.TemporaryDirectory(prefix="cordii-bottleneck-") as tmp:
                workspace = seed_workspace(task, Path(tmp))
                for rel, text in files.items():
                    target = workspace / rel
                    if text is None:
                        if target.exists():
                            target.unlink()
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding="utf-8", newline="")
                outcome = run_oracle(task, workspace)
            passed = outcome.get("passed") if isinstance(outcome, dict) else None
            detail = str(outcome.get("detail", "")) if isinstance(outcome, dict) else ""
            if "oracle timed out" in detail:
                value = (U, detail)
            else:
                value = (tri(passed), detail)
        except Exception as exc:  # an oracle error is UNKNOWN, never FALSE
            value = (U, f"oracle error: {exc}")
        self._cache[key] = value
        return value


# ============================================================================= fact extraction
UNKNOWN_STATE = object()


def _replay_edit(path: str, before: str, args: dict[str, Any]) -> str | None:
    from core.structured_edit import replace_python_symbol, set_json_pointer_value
    replacement, target = args.get("replacement"), args.get("target")
    if not isinstance(replacement, str) or not isinstance(target, str):
        return None
    try:
        if path.endswith(".py"):
            return replace_python_symbol(path, before, target, replacement)[0]
        if path.endswith(".json"):
            return set_json_pointer_value(path, before, target, replacement)[0]
    except Exception:
        return None
    return None


def _replay_non_primitive(tool: str, before: str | None, args: dict[str, Any]) -> Any:
    from core.structured_edit import apply_json_patch, replace_exact, serialize_like
    try:
        if tool == "write_file":
            content = args.get("content")
            return content if isinstance(content, str) else UNKNOWN_STATE
        if tool == "delete_file":
            return None
        if before is None:
            return UNKNOWN_STATE
        if tool == "replace_text":
            old, new = args.get("old"), args.get("new")
            if not isinstance(old, str) or not isinstance(new, str):
                return UNKNOWN_STATE
            return replace_exact(before, old, new)
        if tool == "patch_json":
            set_values, remove = args.get("set"), args.get("remove")
            if isinstance(set_values, dict) and any(not isinstance(v, (str, int, float, bool, list, dict, type(None))) for v in set_values.values()):
                return UNKNOWN_STATE
            doc, _ = apply_json_patch(json.loads(before), set_values if isinstance(set_values, dict) else None, remove if isinstance(remove, list) else None)
            return serialize_like(before, doc)
    except Exception:
        return UNKNOWN_STATE
    return UNKNOWN_STATE


def unguarded_apply(path: str, before: str, target: Any, replacement: Any) -> str | None:
    """Guard judgement only: apply a refused proposal without any guard. None when not appliable."""
    from core.diagnosis import python_symbol_span
    if not isinstance(target, str) or not isinstance(replacement, str) or before is None:
        return None
    if path.endswith(".py"):
        span = python_symbol_span(before, target)
        if span is None:
            return None
        lines = before.splitlines()
        first = lines[span[0] - 1]
        indent = first[: len(first) - len(first.lstrip())]
        block = [(indent + line) if line.strip() else "" for line in textwrap.dedent(replacement).strip("\n").splitlines()]
        return "\n".join(lines[: span[0] - 1] + block + lines[span[1]:]) + ("\n" if before.endswith("\n") else "")
    if path.endswith(".json"):
        try:
            doc, value = json.loads(before), json.loads(replacement)
        except (ValueError, TypeError):
            return None
        segments = _pointer_segments(target) if target.startswith("/") and target != "/" else None
        if not segments:
            return None
        node = doc
        for seg in segments[:-1]:
            if isinstance(node, dict) and seg in node:
                node = node[seg]
            elif isinstance(node, list) and seg.isdigit() and int(seg) < len(node):
                node = node[int(seg)]
            else:
                return None
        last = segments[-1]
        if isinstance(node, dict):
            node[last] = value
        elif isinstance(node, list) and last.isdigit() and int(last) < len(node):
            node[int(last)] = value
        else:
            return None
        return json.dumps(doc, indent=2) + ("\n" if before.endswith("\n") else "")
    return None


def _file_valid(path: str, text: str) -> bool:
    try:
        if path.endswith(".py"):
            compile(text, path, "exec")
        elif path.endswith(".json"):
            json.loads(text)
        return True
    except (SyntaxError, ValueError):
        return False


def guard_reason(result_head: str) -> str:
    if STRUCTURAL_NOOP_TEXT in result_head:
        return "structural_noop"
    matches = [key for key, text in frozen_edit_failure_reasons().items() if text in result_head]
    if len(matches) == 1:
        return matches[0]
    if any(t in result_head for t in PRECONDITION_TEXTS):
        return "precondition"
    if any(t in result_head for t in BLOCKED_TEXTS):
        return "blocked_repeat"
    return "other_guard"


def _definition_node(text: str, target: str) -> ast.AST | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    name = normalize_python_target(target)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return node
        if isinstance(node, ast.ClassDef) and "." in name and node.name == name.split(".")[0]:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == name.split(".")[1]:
                    return child
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node
    return None


def _shape(stmts: list[ast.stmt]) -> tuple:
    out = []
    for s in stmts:
        nested = tuple(_shape(getattr(s, attr)) for attr in ("body", "orelse", "finalbody") if isinstance(getattr(s, attr, None), list))
        handlers = tuple(_shape(h.body) for h in getattr(s, "handlers", []) or [])
        out.append((type(s).__name__, nested, handlers))
    return tuple(out)


def _flat_statements(stmts: list[ast.stmt]) -> list[ast.stmt]:
    out: list[ast.stmt] = []
    for s in stmts:
        out.append(s)
        for attr in ("body", "orelse", "finalbody"):
            child = getattr(s, attr, None)
            if isinstance(child, list):
                out.extend(_flat_statements(child))
        for h in getattr(s, "handlers", []) or []:
            out.extend(_flat_statements(h.body))
    return out


def _header_dump(stmt: ast.stmt) -> str:
    """A statement without its nested statement lists (so parent and child differences are not double counted)."""
    clone = ast.parse(ast.unparse(stmt)).body[0] if hasattr(ast, "unparse") else stmt
    for attr in ("body", "orelse", "finalbody", "handlers"):
        if isinstance(getattr(clone, attr, None), list):
            setattr(clone, attr, [])
    return ast.dump(clone, include_attributes=False)


def content_dimensions(before_def: ast.AST, after_def: ast.AST) -> set[str]:
    """F6 descriptive dimensions for one edit. Returns {'cosmetic_restatement'} when AST-equal."""
    if ast.dump(before_def, include_attributes=False) == ast.dump(after_def, include_attributes=False):
        return {"cosmetic_restatement"}
    dims: set[str] = set()
    if isinstance(before_def, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(after_def, (ast.FunctionDef, ast.AsyncFunctionDef)):
        sig = lambda d: (type(d).__name__, d.name, ast.dump(d.args, include_attributes=False),  # noqa: E731
                         [ast.dump(x, include_attributes=False) for x in d.decorator_list], ast.dump(d.returns, include_attributes=False) if d.returns else None)
        if sig(before_def) != sig(after_def):
            dims.add("signature")
        before_body, after_body = before_def.body, after_def.body
    elif isinstance(before_def, ast.ClassDef) and isinstance(after_def, ast.ClassDef):
        before_body, after_body = before_def.body, after_def.body
    else:
        before_body, after_body = [before_def], [after_def]
    if _shape(before_body) != _shape(after_body):
        dims.add("algorithm")
    else:
        changed = sum(1 for a, b in zip(_flat_statements(before_body), _flat_statements(after_body)) if _header_dump(a) != _header_dump(b))
        if changed == 1:
            dims.add("condition_value_formula")
        elif changed > 1:
            dims.add("multiple_expression_statements")
    return dims


def f6_subtype(per_edit_dims: list[set[str] | None], final_detail: str | None) -> str:
    if not per_edit_dims or any(d is None for d in per_edit_dims):
        return "UNDETERMINED_SUBTYPE"
    union: set[str] = set().union(*per_edit_dims)
    if union == {"cosmetic_restatement"}:
        return "cosmetic_restatement"
    union.discard("cosmetic_restatement")
    if final_detail is not None:
        passed = re.search(r"(\d+) passed", final_detail)
        failed = re.search(r"(\d+) failed", final_detail)
        if passed and failed and int(passed.group(1)) > 0 and int(failed.group(1)) > 0:
            union.add("incomplete_repair")
    if "multiple_expression_statements" in union:
        return "MULTIPLE"
    if "json_value" in union:
        return "OTHER" if len(union) == 1 else "MULTIPLE"
    if len(union) == 1:
        return next(iter(union))
    if len(union) > 1:
        return "MULTIPLE"
    return "OTHER"


def extract_facts(row: dict[str, Any], task: Any, replayer: OracleReplayer, defect_lines: Callable[[str, str], set[int]],
                  repos_dir: Path, normalize: Callable[[str], str], capabilities: dict[str, bool] | None = None) -> TrajectoryFacts:
    facts = _extract_facts(row, task, replayer, defect_lines, repos_dir, normalize)
    facts.d0_harness, facts.d0_contract, _ = d0_task(task, capabilities, repos_dir, normalize)
    return facts


def _extract_facts(row: dict[str, Any], task: Any, replayer: OracleReplayer, defect_lines: Callable[[str, str], set[int]],
                   repos_dir: Path, normalize: Callable[[str], str]) -> TrajectoryFacts:
    gold = [normalize(g) for g in task.gold_files]
    reference = {normalize(k): v for k, v in (task.reference_patch or {}).items()}
    seed: dict[str, str | None] = {}
    for g in gold:
        p = repos_dir / task.repo / g
        seed[g] = p.read_text(encoding="utf-8") if p.is_file() else None

    # D1 / D2
    regions: dict[str, set[int]] = {}
    relevant_py: dict[str, set[str] | None] = {}
    changed_json: dict[str, list[tuple[str, ...]] | None] = {}
    defect_known = T if gold else U
    for g in gold:
        if seed[g] is None or g not in reference:
            defect_known = U
            continue
        if g.endswith(".py"):
            regions[g] = widened_defect_region(seed[g], reference[g], defect_lines)
            existing = relevant_python_symbols(seed[g], regions[g]) or set()
            added = reference_added_python_names(seed[g], reference[g])
            relevant_py[g] = (existing | added) or None
            if relevant_py[g] is None:
                defect_known = U
        elif g.endswith(".json"):
            try:
                changed_json[g] = json_changed_locations(json.loads(seed[g]), json.loads(reference[g])) or None
            except ValueError:
                changed_json[g] = None
            if changed_json[g] is None:
                defect_known = U
        else:
            defect_known = U

    calls = row.get("calls")
    if not isinstance(calls, list):
        return TrajectoryFacts(defect_known=defect_known, evidence=U, usable_diagnosis=U, localized=U, final_correct=U)

    diagnosis_attempted = F
    for c in calls:
        if not isinstance(c, dict) or "tool" not in c:
            diagnosis_attempted = tri_any([diagnosis_attempted, U])
        elif c.get("tool") == "diagnose" and normalize(str((c.get("args") or {}).get("path") or "")) in gold:
            diagnosis_attempted = T
            break

    # D3
    first_round: dict[str, int] = {}
    for c in calls:
        path = normalize(str((c.get("args") or {}).get("path") or ""))
        if c.get("tool") in ("diagnose", "edit_symbol") and path in gold and isinstance(c.get("round"), int):
            first_round.setdefault(path, c["round"])
    views = row.get("read_views")
    per_file: list[Tri] = []
    for g in gold:
        if g not in regions and g not in changed_json:
            continue
        if not isinstance(views, list):
            per_file.append(U)
            continue
        limit = first_round.get(g, float("inf"))
        malformed = any(not isinstance(v, dict) or "path" not in v or not isinstance(v.get("round"), int) for v in views)
        before = [v for v in views if isinstance(v, dict) and v.get("path") == g and isinstance(v.get("round"), int) and v["round"] <= limit]
        completes = [v.get("complete") for v in before]
        if any(x is True for x in completes):
            per_file.append(T)
        elif malformed:
            per_file.append(U)  # an unreadable view record might have been a complete read
        elif all(x is False for x in completes):
            per_file.append(F)  # includes: no view of the file at all
        else:
            per_file.append(U)
    evidence = tri_and(*per_file) if per_file else U

    # D4 / D5
    diagnoses = row.get("diagnoses")
    if not isinstance(diagnoses, list):
        usable, localized = U, U
    else:
        usable_values, localized_values = [], []
        for d in diagnoses:
            if not isinstance(d, dict) or "path" not in d:
                usable_values.append(U)
                localized_values.append(U)
                continue
            if d.get("path") not in gold:
                continue
            if not all(k in d for k in ("success", "refused", "target")):
                usable_values.append(U)
                localized_values.append(U)
                continue
            if d["success"] is True:
                u = T if (d["refused"] is None and d["target"] is not None) else F
            elif d["success"] is False:
                u = F
            else:
                u = U
            usable_values.append(u)
            if u is F:
                continue
            if u is U or d.get("snapshot_matches_seed") is False or "hits_defect" not in d:
                localized_values.append(U)
            else:
                localized_values.append(tri(d["hits_defect"]))
        usable, localized = tri_any(usable_values), tri_any(localized_values)

    # D6-D12 by replaying the ordered call sequence
    fmt = frozen_format_classifier()
    records = row.get("edit_proposals")
    edit_calls = [c for c in calls if isinstance(c, dict) and c.get("tool") == "edit_symbol"]
    use_records = isinstance(records, list) and len(records) == len(edit_calls)
    records_mismatch = isinstance(records, list) and not use_records  # instrumentation exists but cannot be paired
    files: dict[str, Any] = {}
    state_known = not records_mismatch and all(isinstance(c, dict) for c in calls)
    state_correct: list[Tri] = []
    correct_indices: list[int] = []
    last_detail: str | None = None
    mutation_index = -1
    gold_mutation_after: dict[int, bool] = {}
    proposals: list[ProposalFacts] = []
    non_primitive: list[str] = []
    per_edit_dims: list[set[str] | None] = []
    edit_counter = 0

    def current(path: str) -> Any:
        if not state_known:
            return UNKNOWN_STATE
        return files[path] if path in files else seed.get(path, _seed_any(task, repos_dir, path))

    def snapshot() -> dict[str, str | None] | None:
        return dict(files) if state_known else None

    for c in calls:
        if not isinstance(c, dict):
            continue
        tool = c.get("tool")
        if tool not in MUTATING:
            continue
        args = c.get("args") or {}
        path = normalize(str(args.get("path") or ""))
        success = tri(c.get("success"))
        if success is U:
            state_known = False  # a mutation of unknown outcome makes every later workspace state unknown
        if tool == "edit_symbol":
            rec = records[edit_counter] if use_records else None
            edit_counter += 1
            source = rec if isinstance(rec, dict) else args
            target, replacement = source.get("target"), source.get("replacement")
            if path not in gold:
                if success is T:
                    mutation_index += 1
                    after = rec.get("after_text") if isinstance(rec, dict) else _replay_edit(path, current(path), args) if isinstance(current(path), str) else None
                    if isinstance(after, str) and state_known:
                        files[path] = after
                    else:
                        state_known = False
                    state_correct.append(replayer.run(task, snapshot())[0] if snapshot() is not None else U)
                continue
            before = current(path)
            relevance = python_relevance(target, relevant_py.get(path)) if path.endswith(".py") else json_relevance(target, changed_json.get(path))
            if before is UNKNOWN_STATE:
                resolves = valid = U
            else:
                terminal, _ = fmt.classify({"path": source.get("path", args.get("path")), "selector_kind": source.get("selector_kind", args.get("selector_kind")),
                                            "target": target, "replacement": replacement}, before)
                resolves = F if terminal == fmt.SELECTOR_FAILURE else U if terminal == fmt.UNCLASSIFIABLE else T
                valid = T if terminal == fmt.VALID else U if terminal == fmt.UNCLASSIFIABLE else F
            pf = ProposalFacts(index=len(proposals), path=path, target=target, relevant=relevance, resolves=resolves, valid=valid,
                               accepted=success, result_head=str(c.get("result_head") or ""))
            proposals.append(pf)
            if tri_and(relevance, resolves, valid) is T and success is F:
                pf.guard_reason = guard_reason(pf.result_head)
                applied = unguarded_apply(path, before, target, replacement) if isinstance(before, str) else None
                if applied is None or not state_known:
                    pf.guard_judgement = GUARD_C
                elif not _file_valid(path, applied):
                    pf.guard_judgement = GUARD_A
                else:
                    trial = {**files, path: applied}
                    verdict = replayer.run(task, trial)[0]
                    pf.guard_judgement = {T: GUARD_B, F: GUARD_A, U: GUARD_C}[verdict]
            if success is T:
                mutation_index += 1
                after = rec.get("after_text") if isinstance(rec, dict) else (_replay_edit(path, before, args) if isinstance(before, str) else None)
                if isinstance(after, str) and state_known:
                    files[path] = after
                    if tri_and(relevance, resolves, valid) is T and path.endswith(".py") and isinstance(before, str) and isinstance(target, str):
                        b, a = _definition_node(before, target), _definition_node(after, target)
                        per_edit_dims.append(content_dimensions(b, a) if b is not None and a is not None else None)
                    elif tri_and(relevance, resolves, valid) is T and path.endswith(".json"):
                        per_edit_dims.append({"json_value"})
                else:
                    state_known = False
                    if tri_and(relevance, resolves, valid) is T:
                        per_edit_dims.append(None)
                gold_mutation_after[mutation_index] = True
                verdict, detail = replayer.run(task, snapshot()) if snapshot() is not None else (U, None)
                state_correct.append(verdict)
                last_detail = detail
                if verdict is T:
                    correct_indices.append(mutation_index)
            continue
        # non-primitive mutating tools
        if path in gold:
            non_primitive.append(tool)
        if success is T:
            mutation_index += 1
            outcome = _replay_non_primitive(tool, current(path) if isinstance(current(path), str) else None, args)
            if outcome is UNKNOWN_STATE or not state_known:
                state_known = False
            else:
                files[path] = outcome
            if path in gold:
                gold_mutation_after[mutation_index] = True
            verdict, detail = replayer.run(task, snapshot()) if snapshot() is not None else (U, None)
            state_correct.append(verdict)
            last_detail = detail
            if verdict is T:
                correct_indices.append(mutation_index)

    final_correct = state_correct[-1] if state_correct else U
    damaged = set(row.get("damaged_files") or []) | set(row.get("invalid_gold_files") or [])
    regression = F
    if correct_indices:
        last_ok = max(correct_indices)
        if any(i > last_ok for i in gold_mutation_after) or any(g in damaged for g in gold):
            regression = T
    subtype = f6_subtype(per_edit_dims, last_detail)
    return TrajectoryFacts(defect_known=defect_known, diagnosis_attempted=diagnosis_attempted, evidence=evidence, usable_diagnosis=usable, localized=localized, proposals=proposals,
                           gold_edit_proposal_exists=bool(proposals), non_primitive_attempts=non_primitive, state_correct=state_correct,
                           final_correct=final_correct, regression_evidence=regression, agent_escalation=row.get("agent_escalation"),
                           model_claimed_done=row.get("model_claimed_done"), rounds=row.get("rounds"), f6_subtype=subtype)


def _seed_any(task: Any, repos_dir: Path, path: str) -> str | None:
    p = repos_dir / task.repo / path
    return p.read_text(encoding="utf-8") if p.is_file() else None


def classify_row(row: dict[str, Any], task: Any, replayer: OracleReplayer | None = None) -> BottleneckResult:
    from benchmark import repo_task_eval as rte
    from core.path_candidates import normalize
    condition = row.get("condition")
    caps = action_capabilities(rte.CONDITIONS.get(condition, {}).get("overrides")) if isinstance(condition, str) and condition in rte.CONDITIONS else None
    facts = extract_facts(row, task, replayer or OracleReplayer(), rte.defect_lines, rte.REPOS_DIR, normalize, caps)
    return classify(facts)
