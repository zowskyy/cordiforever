"""Synthetic tests for the Furthest-Reached Bottleneck Taxonomy (benchmark/analysis/furthest_bottleneck_taxonomy.md).
Synthetic rows only (built on corpus seed files and task reference patches); no frozen trajectory row is read."""

from __future__ import annotations

import ast
import copy
import dataclasses
import json

import pytest

import benchmark.analysis.furthest_bottleneck as fb
from benchmark.analysis.furthest_bottleneck import F, T, U, BottleneckResult, OracleReplayer, ProposalFacts, TrajectoryFacts
from benchmark.repo_task_eval import REPOS_DIR
from benchmark.repo_tasks import TASKS_BY_NAME

DIV = TASKS_BY_NAME["mathlib_divide_zero"]
CFG = TASKS_BY_NAME["config_add_feature"]
OPS = "mathlib/operations.py"
APP = "config/app.json"
OPS_SEED = (REPOS_DIR / "mathlib" / OPS).read_text(encoding="utf-8")
FIX = "def divide(a, b):\n    if b == 0:\n        raise ValueError(\"division by zero\")\n    return a / b"
RESTATED = "def divide(a, b):\n    return (a / b)"
WRONG_OP = "def divide(a, b):\n    return a // b"


class FakeReplayer:
    """Deterministic stand-in for the oracle: passes iff the task's reference behavior marker is present."""

    def __init__(self, verdict=None):
        self.calls: list[dict] = []
        self.verdict = verdict

    def run(self, task, files):
        self.calls.append(dict(files))
        if self.verdict is not None:
            return self.verdict, "fake"
        if task.name.startswith("mathlib"):
            text = files.get(OPS, OPS_SEED)
            return (T if isinstance(text, str) and "raise ValueError" in text else F), "1 passed" if text and "raise ValueError" in text else "1 failed"
        text = files.get(APP)
        return (T if text and '"search"' in text else F), "fake"


def call(rnd, tool, success=True, head="", **args):
    return {"round": rnd, "tool": tool, "args": args, "success": success, "result_head": head}


def edit(rnd, target, replacement, success=True, head="", path=OPS, kind="python_symbol"):
    return call(rnd, "edit_symbol", success, head, path=path, selector_kind=kind, target=target, replacement=replacement)


def row(edits=(), read_complete=True, diagnosis=None, extra_calls=(), **fields):
    diag = diagnosis if diagnosis is not None else [{"path": OPS, "success": True, "refused": None, "target": "divide", "hits_defect": True, "snapshot_matches_seed": None}]
    base = {
        "calls": [call(1, "read_file", path=OPS), call(2, "diagnose", path=OPS, target="divide")] + list(extra_calls) + list(edits),
        "read_views": [{"round": 1, "path": OPS, "complete": read_complete}] if read_complete is not None else [{"round": 1, "path": OPS, "complete": None}],
        "diagnoses": diag, "damaged_files": [], "invalid_gold_files": [], "agent_escalation": None, "model_claimed_done": True, "rounds": 5,
        "condition": "qwen_selectorkind",
    }
    base.update(fields)
    return base


def label(r, task=DIV, replayer=None):
    return fb.classify_row(r, task, replayer or FakeReplayer())


# ============================================================================ tri-state invariant
@pytest.mark.parametrize("value", [None, 0, 1, "", "True", "False", [], {}, object()])
def test_tri_only_literal_booleans_are_known(value):
    assert fb.tri(value) is U


def test_tri_combinators():
    assert fb.tri(True) is T and fb.tri(False) is F
    assert fb.tri_and(T, U) is U and fb.tri_and(U, F) is F and fb.tri_and(T, T) is T
    assert fb.tri_any([F, U]) is U and fb.tri_any([U, T]) is T and fb.tri_any([]) is F and fb.tri_any([F, F]) is F


# ============================================================================ bottleneck labels (extraction on synthetic rows)
def test_01_no_read_and_no_diagnosis_is_F0():
    r = row(read_complete=False, diagnosis=[{"path": OPS, "success": False, "refused": "evidence_requires_read", "target": None, "hits_defect": False}])
    res = label(r)
    assert (res.label, res.sub_label) == ("F0", "evidence_not_acquired")


def test_02_incomplete_read_but_correct_localization_is_not_F0():
    res = label(row(read_complete=False))
    assert res.label == "F2"


def test_03_diagnosis_misses_defect_is_F1():
    r = row(diagnosis=[{"path": OPS, "success": True, "refused": None, "target": "add", "hits_defect": False, "snapshot_matches_seed": None}])
    assert (label(r).label, label(r).sub_label) == ("F1", "diagnosis_misses_defect")


def test_04_no_usable_diagnosis_with_evidence_is_F1():
    r = row(diagnosis=[{"path": OPS, "success": False, "refused": None, "target": None, "hits_defect": False}])
    assert (label(r).label, label(r).sub_label) == ("F1", "diagnosis_attempted_unusable")


def test_05_wrong_target_edit_is_F1_not_F6():
    r = row(edits=[edit(3, "multiply", "def multiply(a, b):\n    return b * a")])
    res = label(r)
    assert (res.label, res.sub_label) == ("F1", "edit_targets_wrong_location")


def test_06_localized_without_edit_is_F2_with_stop_sub_label():
    assert label(row()).sub_label == "premature_done"
    assert label(row(model_claimed_done=False, agent_escalation="repeated_failed_call")).sub_label == "escalation:repeated_failed_call"
    assert label(row(model_claimed_done=False, rounds=12)).sub_label == "stall_or_max_rounds"


def test_07_only_refused_non_primitive_attempt_is_F2():
    r = row(extra_calls=[call(3, "write_file", False, "already exists", path=OPS, content=OPS_SEED)])
    res = label(r)
    assert res.label == "F2" and res.sub_label == "non_primitive_mutation_attempt_only:write_file"
    assert "non_primitive:write_file" in res.history


def test_08_relevant_unresolved_selector_is_F3():
    res = label(row(edits=[edit(3, "/divide", FIX, success=False, head="is not a function")]))
    assert res.label == "F3"


def test_09_wrong_intent_unresolved_selector_is_F1():
    res = label(row(edits=[edit(3, "nonexistent", "def nonexistent():\n    return 1", success=False)]))
    assert (res.label, res.sub_label) == ("F1", "edit_targets_wrong_location")


def test_10_structure_format_failures_are_F4():
    assert label(row(edits=[edit(3, "divide", OPS_SEED, success=False, head="also redefines")])).label == "F4"
    json_row = row(diagnosis=[{"path": APP, "success": True, "refused": None, "target": "/features", "hits_defect": True}],
                   edits=[edit(3, "/features", "search", success=False, path=APP, kind="json_pointer")], read_views=[{"round": 1, "path": APP, "complete": True}])
    assert label(json_row, CFG).label == "F4"
    kind_row = dict(json_row, calls=json_row["calls"][:2] + [edit(3, "/features", '"search"', success=False, path=APP, kind="json_pointer")])
    assert label(kind_row, CFG).label == "F4"


def test_11_guard_rejection_is_F5_with_descriptive_judgements():
    res = label(row(edits=[edit(3, "divide", FIX, success=False, head="replacement also redefines x, which already exist")]))
    assert res.label == "F5" and res.sub_label == "clobbers_existing" and res.guard == [("clobbers_existing", fb.GUARD_B)]
    res_a = label(row(edits=[edit(3, "divide", RESTATED, success=False, head="Replacement is structurally equivalent to the current definition")]))
    assert res_a.label == "F5" and res_a.guard == [("structural_noop", fb.GUARD_A)]


def test_11c_guard_judgement_C_when_replay_unknown_does_not_change_label():
    res = label(row(edits=[edit(3, "divide", FIX, success=False, head="also redefines")]), replayer=FakeReplayer(verdict=U))
    assert res.label == "F5" and res.guard == [("clobbers_existing", fb.GUARD_C)]


def test_11d_refused_proposal_with_unknown_pre_state_is_UNDETERMINED_not_F5_or_F4():
    truncated = {"chars": 999, "sha256": "0" * 16, "head": "def multiply("}
    res = label(row(edits=[edit(3, "multiply", truncated, success=True), edit(4, "divide", FIX, success=False, head="also redefines")]))
    assert res.label == "UNDETERMINED"


def test_12_structural_noop_reason():
    res = label(row(edits=[edit(3, "divide", RESTATED, success=False, head="Replacement is structurally equivalent to the current definition and does not constitute a substantive edit.")]))
    assert res.sub_label == "structural_noop"


def test_13_accepted_but_incorrect_is_F6_with_subtype():
    res = label(row(edits=[edit(3, "divide", WRONG_OP)]))
    assert res.label == "F6" and res.f6_subtype == "condition_value_formula"


@pytest.mark.parametrize("before,after,expected", [
    ("def f(a):\n    return a < 1", "def f(a):\n    return (a < 1)", {"cosmetic_restatement"}),
    ("def f(a):\n    return a < 1", "def f(a):\n    return a <= 1", {"condition_value_formula"}),
    ("def f(a):\n    return a", "def f(a):\n    if a:\n        return 0\n    return a", {"algorithm"}),
    ("def f(a):\n    return a", "def f(a, b):\n    return a", {"signature"}),
    ("def f(a):\n    return a", "def f(a, b):\n    return b", {"signature", "condition_value_formula"}),
    ("def f(a):\n    x = 1\n    return a + 2", "def f(a):\n    x = 5\n    return a + 7", {"multiple_expression_statements"}),
    ("def f(a):\n    if a > 1:\n        return 1\n    return 0", "def f(a):\n    if a >= 1:\n        return 1\n    return 0", {"condition_value_formula"}),
])
def test_13b_content_dimensions(before, after, expected):
    assert fb.content_dimensions(ast.parse(before).body[0], ast.parse(after).body[0]) == expected


@pytest.mark.parametrize("dims,detail,expected", [
    ([{"cosmetic_restatement"}], None, "cosmetic_restatement"),
    ([{"signature", "condition_value_formula"}], None, "MULTIPLE"),
    ([{"algorithm", "condition_value_formula"}], None, "MULTIPLE"),
    ([{"multiple_expression_statements"}], None, "MULTIPLE"),
    ([{"condition_value_formula"}], "2 passed, 1 failed", "MULTIPLE"),
    ([{"condition_value_formula"}], "1 failed", "condition_value_formula"),
    ([{"json_value"}], None, "OTHER"),
    ([{"condition_value_formula"}, None], None, "UNDETERMINED_SUBTYPE"),
    ([], None, "UNDETERMINED_SUBTYPE"),
])
def test_13c_f6_subtype_never_over_precise(dims, detail, expected):
    assert fb.f6_subtype(dims, detail) == expected


def test_14_correct_then_regressed_with_evidence_is_F7():
    res = label(row(edits=[edit(3, "divide", FIX), edit(4, "divide", WRONG_OP)]))
    assert res.label == "F7"


def test_14b_correct_state_without_positive_regression_evidence_is_UNDETERMINED():
    facts = TrajectoryFacts(defect_known=T, d0_harness=T, evidence=T, usable_diagnosis=T, localized=T,
                            proposals=[ProposalFacts(0, OPS, "divide", T, T, T, T)], gold_edit_proposal_exists=True,
                            state_correct=[T, F], final_correct=F, regression_evidence=F)
    assert fb.classify(facts).label == "UNDETERMINED"


def test_15_final_state_passes_but_row_failed_is_F8():
    res = label(row(edits=[edit(3, "divide", FIX)]))
    assert res.label == "F8"


def test_16_truncated_successful_argument_is_UNDETERMINED_not_F6():
    truncated = {"chars": 999, "sha256": "0" * 16, "head": "def divide(a, b):\n    if b == 0:"}
    res = label(row(edits=[edit(3, "divide", truncated, success=True)]))
    assert res.label == "UNDETERMINED"


def test_17_later_progress_overrides_earlier_failure_and_history_is_kept():
    res = label(row(edits=[edit(3, "/divide", FIX, success=False), edit(4, "divide", FIX, success=False, head="also redefines")]))
    assert res.label == "F5"
    assert res.history[0] == "proposal0:F3_selector" and res.history[1] == "proposal1:F5_guard"


def test_18_deterministic_single_label_and_inputs_unmodified():
    r = row(edits=[edit(3, "/divide", FIX, success=False), edit(4, "divide", WRONG_OP)])
    snapshot = copy.deepcopy(r)
    results = [label(r) for _ in range(3)]
    assert all(x == results[0] for x in results) and r == snapshot
    assert isinstance(results[0], BottleneckResult) and results[0].label in {"F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "UNDETERMINED"}


def test_19_no_computable_defect_region_is_UNDETERMINED():
    no_patch = dataclasses.replace(DIV, reference_patch=None)
    assert label(row(edits=[edit(3, "divide", WRONG_OP)]), no_patch).label == "UNDETERMINED"
    unchanged = dataclasses.replace(DIV, reference_patch={OPS: OPS_SEED})
    assert label(row(edits=[edit(3, "divide", WRONG_OP)]), unchanged).label == "UNDETERMINED"


def test_20_multi_gold_relevance_to_any_defect_region():
    stats_path = "mathlib/stats.py"
    stats_seed = (REPOS_DIR / "mathlib" / stats_path).read_text(encoding="utf-8")
    median_ref = stats_seed.replace("def median", "def median", 1) + "\n# changed\n"
    spans = fb.python_symbol_spans(stats_seed)
    last_name = max(spans, key=lambda n: spans[n][1])
    multi = dataclasses.replace(DIV, gold_files=(OPS, stats_path), reference_patch={OPS: DIV.reference_patch[OPS], stats_path: median_ref})
    facts = fb.extract_facts(row(edits=[edit(3, last_name, "def %s(values):\n    return 0" % last_name, path=stats_path)],
                                 read_views=[{"round": 1, "path": OPS, "complete": True}, {"round": 1, "path": stats_path, "complete": True}]),
                             multi, FakeReplayer(), __import__("benchmark.repo_task_eval", fromlist=["x"]).defect_lines, REPOS_DIR, lambda p: p)
    assert facts.defect_known is T and facts.proposals[0].relevant is T


# ============================================================================ JSON structural relevance
@pytest.mark.parametrize("target,changed,expected", [
    ("/features", [("features",)], T),                       # the changed location itself
    ("/features/0", [("features",)], T),                     # child inside a replaced subtree
    ("/database", [("database", "host")], T),                 # immediate parent container
    ("/a", [("a", "b", "c")], F),                             # over-broad ancestor
    ("/", [("features",)], F),                                # root
    ("", [("features",)], F),                                 # root
    ("/name", [("features",)], F),                            # unrelated
    ("/features", None, U),                                   # unknown changed set
    (None, [("features",)], U),                               # target not a string
])
def test_json_structural_relevance(target, changed, expected):
    assert fb.json_relevance(target, changed) is expected


def test_json_changed_locations():
    assert fb.json_changed_locations({"f": ["a"]}, {"f": ["a", "b"]}) == [("f",)]
    assert fb.json_changed_locations({"d": {"h": "x", "p": 1}}, {"d": {"h": "y", "p": 1}}) == [("d", "h")]
    assert fb.json_changed_locations({"a": 1}, {"a": 1, "b": 2}) == [("b",)]
    assert fb.json_changed_locations({"a": True}, {"a": 1}) == [("a",)]


def test_python_relevance_normalization():
    rel = {"divide", "Store.total"}
    for target in ("divide", "/divide", "def divide(a, b):", "async def divide", "total", "Store.total"):
        assert fb.python_relevance(target, rel) is T
    assert fb.python_relevance("multiply", rel) is F
    assert fb.python_relevance("divide", None) is U and fb.python_relevance(None, rel) is U


# ============================================================================ D11 reconstruction
def test_d11_includes_preceding_successful_non_edit_mutation():
    replayer = FakeReplayer()
    label(row(extra_calls=[call(3, "write_file", True, path="notes.txt", content="hello")], edits=[edit(4, "divide", FIX)]), replayer=replayer)
    assert all(state.get("notes.txt") == "hello" for state in replayer.calls)


def test_d11_unreconstructable_preceding_mutation_is_UNDETERMINED():
    truncated = {"chars": 999, "sha256": "0" * 16, "head": "hello"}
    res = label(row(extra_calls=[call(3, "write_file", True, path="notes.txt", content=truncated)], edits=[edit(4, "divide", FIX)]))
    assert res.label == "UNDETERMINED"


def test_d11_uses_after_text_from_edit_proposals():
    fixed = OPS_SEED.replace("def divide(a, b):\n    return a / b", FIX)
    r = row(edits=[edit(3, "divide", FIX)])
    r["edit_proposals"] = [{"path": OPS, "selector_kind": "python_symbol", "target": "divide", "replacement": FIX, "success": True, "after_text": fixed}]
    replayer = FakeReplayer()
    assert label(r, replayer=replayer).label == "F8" and replayer.calls[-1][OPS] == fixed


def test_d11_edit_proposals_count_mismatch_is_unknown_not_false():
    r = row(edits=[edit(3, "divide", WRONG_OP)])
    r["edit_proposals"] = []
    assert label(r).label == "UNDETERMINED"


# ============================================================================ UNKNOWN != FALSE (extraction)
def test_unknown_diagnosis_fields_do_not_become_F0_or_F1():
    r = row(diagnosis=[{"path": OPS, "refused": None, "target": "divide"}])  # success missing
    assert label(r).label == "UNDETERMINED"


def test_unknown_diagnosis_path_does_not_become_F1():
    r = row(diagnosis=[{"success": True, "refused": None, "target": "divide", "hits_defect": True}])
    assert label(r).label == "UNDETERMINED"


def test_unknown_read_completeness_does_not_become_F0():
    r = row(read_complete=None, diagnosis=[{"path": OPS, "success": False, "refused": None, "target": None}])
    assert label(r).label == "UNDETERMINED"


def test_malformed_read_view_does_not_become_F0():
    r = row(read_views=[{"path": OPS, "complete": False}], diagnosis=[{"path": OPS, "success": False, "refused": None, "target": None}])
    assert label(r).label == "UNDETERMINED"


def test_snapshot_mismatch_localization_is_unknown():
    r = row(diagnosis=[{"path": OPS, "success": True, "refused": None, "target": "divide", "hits_defect": False, "snapshot_matches_seed": False}])
    assert label(r).label == "UNDETERMINED"


def test_missing_success_on_edit_is_unknown_acceptance():
    r = row(edits=[{"round": 3, "tool": "edit_symbol", "args": {"path": OPS, "selector_kind": "python_symbol", "target": "divide", "replacement": WRONG_OP}, "result_head": ""}])
    assert label(r).label == "UNDETERMINED"


def test_correct_state_with_unknown_final_state_is_UNDETERMINED_not_F8():
    facts = TrajectoryFacts(defect_known=T, d0_harness=T, evidence=T, usable_diagnosis=T, localized=T,
                            proposals=[ProposalFacts(0, OPS, "divide", T, T, T, T)], gold_edit_proposal_exists=True,
                            state_correct=[T, U], final_correct=U, regression_evidence=T)
    res = fb.classify(facts)
    assert (res.label, res.sub_label) == ("UNDETERMINED", "final_state_correctness_unknown")


def test_mutation_with_unknown_outcome_makes_later_states_unknown():
    unknown_write = {"round": 3, "tool": "write_file", "args": {"path": "notes.txt", "content": "hello"}, "result_head": ""}  # success missing
    res = label(row(extra_calls=[unknown_write], edits=[edit(4, "divide", FIX)]))
    assert res.label == "UNDETERMINED"


def test_refused_truncated_relevant_proposal_is_UNDETERMINED_not_F5():
    truncated = {"chars": 999, "sha256": "0" * 16, "head": "def divide(a, b):\n    if b == 0:"}
    res = label(row(edits=[edit(3, "divide", truncated, success=False, head="also redefines")]))
    assert res.label == "UNDETERMINED"


def test_oracle_unknown_does_not_become_F6():
    res = label(row(edits=[edit(3, "divide", WRONG_OP)]), replayer=FakeReplayer(verdict=U))
    assert res.label == "UNDETERMINED"


def test_missing_calls_field_is_unknown():
    r = row()
    del r["calls"]
    assert label(r).label == "UNDETERMINED"


def test_pure_classifier_unknown_at_each_decisive_stage():
    def facts(**kw):
        base = dict(defect_known=T, d0_harness=T, evidence=T, usable_diagnosis=T, localized=T, proposals=[], gold_edit_proposal_exists=False)
        base.update(kw)
        return TrajectoryFacts(**base)
    p = lambda *v: ProposalFacts(0, OPS, "divide", *v)  # noqa: E731
    assert fb.classify(facts(defect_known=U)).label == "UNDETERMINED"
    assert fb.classify(facts(proposals=[p(U, F, F, F)], gold_edit_proposal_exists=True)).label == "UNDETERMINED"
    assert fb.classify(facts(proposals=[p(T, U, F, F)], gold_edit_proposal_exists=True)).label == "UNDETERMINED"
    assert fb.classify(facts(proposals=[p(T, T, U, F)], gold_edit_proposal_exists=True)).label == "UNDETERMINED"
    assert fb.classify(facts(proposals=[p(T, T, T, U)], gold_edit_proposal_exists=True)).label == "UNDETERMINED"
    assert fb.classify(facts(proposals=[p(T, T, T, T)], gold_edit_proposal_exists=True, state_correct=[U], final_correct=U)).label == "UNDETERMINED"
    assert fb.classify(facts(localized=U)).label == "UNDETERMINED"
    assert fb.classify(facts(localized=F, usable_diagnosis=U)).label == "UNDETERMINED"
    assert fb.classify(facts(localized=F, usable_diagnosis=F, evidence=U)).label == "UNDETERMINED"
    # known values still classify
    assert fb.classify(facts(localized=F, usable_diagnosis=F, evidence=F)).label == "F0"
    assert fb.classify(facts(proposals=[p(T, T, T, T)], gold_edit_proposal_exists=True, state_correct=[F], final_correct=F, f6_subtype="OTHER")).label == "F6"


def test_guard_judgement_never_changes_label():
    base = dict(defect_known=T, d0_harness=T, evidence=T, usable_diagnosis=T, localized=T, gold_edit_proposal_exists=True)
    labels = set()
    for judgement in (fb.GUARD_A, fb.GUARD_B, fb.GUARD_C, None):
        pf = ProposalFacts(0, OPS, "divide", T, T, T, F, guard_reason="clobbers_existing", guard_judgement=judgement)
        labels.add(fb.classify(TrajectoryFacts(proposals=[pf], **base)).label)
    assert labels == {"F5"}


# ============================================================================ oracle replay (existing oracle, task data only)
def test_real_oracle_replay_seed_fails_and_reference_passes():
    replayer = OracleReplayer()
    assert replayer.run(DIV, {})[0] is F
    assert replayer.run(DIV, {OPS: DIV.reference_patch[OPS]})[0] is T


def test_oracle_error_timeout_and_not_applicable_are_unknown(tmp_path):
    def boom(task, workspace):
        raise RuntimeError("oracle crashed")
    seed = lambda task, dest: (dest / "ws").mkdir() or dest / "ws"  # noqa: E731
    assert OracleReplayer(run_oracle=boom, seed_workspace=seed).run(DIV, {})[0] is U
    assert OracleReplayer(run_oracle=lambda t, w: {"passed": False, "detail": "oracle timed out"}, seed_workspace=seed).run(DIV, {})[0] is U
    assert OracleReplayer(run_oracle=lambda t, w: {"passed": None, "detail": "no hidden tests"}, seed_workspace=seed).run(DIV, {})[0] is U


def test_replay_never_writes_to_frozen_trees(tmp_path):
    before = {p: p.stat().st_mtime_ns for p in (REPOS_DIR / "mathlib").rglob("*") if p.is_file()}
    OracleReplayer().run(DIV, {OPS: "def broken(:\n"})
    after = {p: p.stat().st_mtime_ns for p in (REPOS_DIR / "mathlib").rglob("*") if p.is_file()}
    assert before == after


# ============================================================================ D0 action-space applicability (synthetic repos)
from types import SimpleNamespace  # noqa: E402

LOCALIZED = fb.action_capabilities({"localized_edits": True, "explicit_selector_kind": True, "structured_edits": False})
MOD = "pkg/mod.py"
SEED_MOD = "import os\n\n\ndef keep(a):\n    return a\n\n\ndef divide(a, b):\n    return a / b\n"


def synthetic_task(tmp_path, files, reference, gold=None, name="synthetic"):
    for rel, text in files.items():
        p = tmp_path / "repo" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return SimpleNamespace(name=name, repo="repo", gold_files=tuple(gold or reference), reference_patch=reference)


def d0(tmp_path, files, reference, caps=LOCALIZED, gold=None):
    task = synthetic_task(tmp_path, files, reference, gold)
    harness, contract, _ = fb.d0_task(task, caps, tmp_path, lambda p: p)
    return harness, contract


def test_d0_existing_symbol_replacement_is_true(tmp_path):
    ref = SEED_MOD.replace("return a / b", "if b == 0:\n        raise ValueError\n    return a / b")
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: ref}) == (T, T)


def test_d0_new_top_level_definition_is_harness_true_contract_false(tmp_path):
    ref = SEED_MOD + "\n\ndef power(a, b):\n    return a ** b\n"
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: ref}) == (T, F)


def test_d0_non_selectable_change_is_unknown_not_false_when_alternative_may_exist(tmp_path):
    ref = SEED_MOD.replace("import os", "import os, sys")
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: ref}) == (U, U)


def test_d0_sole_gold_file_without_any_selectable_statement_is_false(tmp_path):
    seed = "import os\nimport sys\n"
    assert d0(tmp_path, {MOD: seed}, {MOD: "import os\nimport json\n"}) == (F, F)


def test_d0_selectable_name_removal_is_unknown(tmp_path):
    ref = SEED_MOD.replace("def keep(a):\n    return a\n\n\n", "")
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: ref})[0] is U


def test_d0_unparseable_reference_is_unknown(tmp_path):
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: "def broken(:\n"}) == (U, U)


def test_d0_json_resolvable_same_kind_is_true_and_root_kind_change_is_false(tmp_path):
    seed = '{"features": ["login"], "port": 1}'
    assert d0(tmp_path, {"c.json": seed}, {"c.json": '{"features": ["login", "search"], "port": 1}'}) == (T, T)
    # a kind change whose only parent is the (unselectable) document root is not provably required or representable: UNKNOWN
    assert d0(tmp_path, {"c.json": seed}, {"c.json": '{"features": ["login"], "port": "1"}'}) == (U, U)
    nested = '{"db": {"port": 1}}'
    assert d0(tmp_path, {"n.json": nested}, {"n.json": '{"db": {"port": "1"}}'}) == (T, T)  # selectable parent object
    assert d0(tmp_path, {"c.json": seed}, {"c.json": '["login"]'}) == (F, F)


def test_d0_reflects_enabled_operations_not_only_edit_symbol(tmp_path):
    ref = SEED_MOD.replace("import os", "import os, sys")
    structured = fb.action_capabilities({"localized_edits": True, "structured_edits": True})
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: ref}, caps=structured) == (T, T)
    overwrite = fb.action_capabilities({"localized_edits": False})
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: ref}, caps=overwrite) == (T, T)
    assert d0(tmp_path, {}, {"pkg/new.py": "def new():\n    return 1\n"}) == (T, T)  # creating a new file is enabled


def test_d0_unknown_configuration_is_unknown(tmp_path):
    assert d0(tmp_path, {MOD: SEED_MOD}, {MOD: SEED_MOD.replace("a / b", "a // b")}, caps=None) == (U, U)
    r = row(edits=[edit(3, "divide", WRONG_OP)])
    del r["condition"]
    assert label(r).label == "UNDETERMINED" and label(r).sub_label == "action_space_applicability_unknown"


def test_d0_task_definition_mathlib_add_power_is_harness_unknown_contract_false():
    task = TASKS_BY_NAME["mathlib_add_power"]
    from core.path_candidates import normalize
    harness, contract, detail = fb.d0_task(task, LOCALIZED, REPOS_DIR, normalize)
    assert harness is U and contract is F
    assert "insert_top_level_statement_adjacent_to_selectable" in detail["mathlib/operations.py"]


def _facts(**kw):
    base = dict(defect_known=T, d0_harness=T, evidence=T, usable_diagnosis=T, localized=T, proposals=[], gold_edit_proposal_exists=False)
    base.update(kw)
    return TrajectoryFacts(**base)


def test_d0_false_is_interface_unsupported_never_f1():
    wrong = ProposalFacts(0, OPS, "power", F, F, F, F)
    res = fb.classify(_facts(d0_harness=F, proposals=[wrong], gold_edit_proposal_exists=True))
    assert res.label == "INTERFACE_UNSUPPORTED"


def test_d0_unknown_is_undetermined():
    assert fb.classify(_facts(d0_harness=U)).label == "UNDETERMINED"


def test_d0_contract_never_changes_label():
    relevant_unresolved = ProposalFacts(0, OPS, "power", T, F, F, F)
    labels = {fb.classify(_facts(d0_contract=c, proposals=[relevant_unresolved], gold_edit_proposal_exists=True)).label for c in (T, F, U)}
    assert labels == {"F3"}
    assert fb.classify(_facts(d0_contract=F, proposals=[relevant_unresolved], gold_edit_proposal_exists=True)).d0_contract == "FALSE"


def test_reference_added_symbol_intent_is_f3_not_f1(tmp_path):
    ref = SEED_MOD + "\n\ndef power(a, b):\n    return a ** b\n"
    task = synthetic_task(tmp_path, {MOD: SEED_MOD}, {MOD: ref})
    r = {"calls": [call(1, "read_file", path=MOD), call(2, "diagnose", path=MOD, target="divide"),
                   edit(3, "power", "def power(a, b):\n    return a ** b", success=False, head="is not a function", path=MOD)],
         "read_views": [{"round": 1, "path": MOD, "complete": True}],
         "diagnoses": [{"path": MOD, "success": True, "refused": None, "target": "divide", "hits_defect": True}],
         "damaged_files": [], "invalid_gold_files": [], "rounds": 4}
    from benchmark.repo_task_eval import defect_lines
    facts = fb.extract_facts(r, task, FakeReplayer(verdict=F), defect_lines, tmp_path, lambda p: p, LOCALIZED)
    res = fb.classify(facts)
    assert facts.d0_harness is T and facts.d0_contract is F
    assert res.label == "F3" and res.d0_contract == "FALSE"


def test_f1_no_diagnosis_attempted_sub_label():
    r = row(diagnosis=[], calls=[call(1, "read_file", path=OPS)])
    res = label(r)
    assert (res.label, res.sub_label) == ("F1", "no_diagnosis_attempted")


def test_guard_judgement_names_are_counterfactual_not_normative():
    assert fb.GUARD_A == "A_protective_against_proposal"
    assert fb.GUARD_B == "B_counterfactually_successful_if_applied"
    assert fb.GUARD_C == "C_undetermined"
