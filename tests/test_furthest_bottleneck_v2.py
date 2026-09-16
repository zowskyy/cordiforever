"""Synthetic tests for the D3-v2 amendment (benchmark/analysis/furthest_bottleneck_taxonomy_v2.md).

Synthetic fixtures only: no frozen trajectory row is read, and no real classification output is used. Where a v1
comparison is needed, v1's own `extract_facts` is called on the same synthetic row.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest

import benchmark.analysis.furthest_bottleneck as v1
import benchmark.analysis.furthest_bottleneck_v2 as v2
from benchmark.analysis.furthest_bottleneck import F, T, U
from benchmark.repo_task_eval import REPOS_DIR, defect_lines
from benchmark.repo_tasks import TASKS_BY_NAME
from core.path_candidates import normalize

ROOT = Path(__file__).resolve().parents[1]
DIV = TASKS_BY_NAME["mathlib_divide_zero"]
OPS = "mathlib/operations.py"
OTHER = "mathlib/other.py"               # a second gold file, used where a multi-file domain is needed
OTHER_NON_GOLD = "mathlib/helpers.py"    # outside every D3 scope used in this suite
SCOPE = [OPS]

FROZEN_V1 = {
    "benchmark/analysis/furthest_bottleneck_taxonomy.md": "cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5",
    "benchmark/analysis/furthest_bottleneck.py": "6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b",
    "benchmark/analysis/furthest_bottleneck_mutations.py": "8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a",
    "tests/test_furthest_bottleneck.py": "055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451",
    "tests/test_furthest_bottleneck_mutations.py": "658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615",
}


class StubReplayer:
    def run(self, task, files):
        return U, "stub"


# ============================================================================= fixture helpers
def diag(rnd, success=False, path=OPS):
    return {"round": rnd, "tool": "diagnose", "args": {"path": path, "target": "divide"}, "success": success, "result_head": ""}


def edit(rnd, success=False, path=OPS):
    return {"round": rnd, "tool": "edit_symbol", "success": success, "result_head": "",
            "args": {"path": path, "selector_kind": "python_symbol", "target": "divide", "replacement": "def divide(a, b):\n    return a / b"}}


def read(rnd, path=OPS):
    return {"round": rnd, "tool": "read_file", "args": {"path": path}, "success": True, "result_head": ""}


def view(rnd, complete=True, path=OPS):
    return {"round": rnd, "path": path, "complete": complete}


def record(refused=None, path=OPS):
    return {"path": path, "success": refused is None, "refused": refused, "pre_read": True,
            "evidence_head": "", "seed_span": None, "localized": False, "hits_defect": False}


def rejection(tool="diagnose", reason="evidence_requires_read", path=OPS):
    return {"reason": reason, "tool": tool, "path": path, "round": 0, "retried": False, "outcome": "unresolved"}


MISSING = object()  # distinguishes "field absent from the row" from "field present and empty"


def row(calls, views, diagnoses=MISSING, rejections=MISSING, **fields):
    base = {"calls": calls, "read_views": views, "damaged_files": [],
            "invalid_gold_files": [], "agent_escalation": None, "model_claimed_done": True, "rounds": 5}
    if diagnoses is not MISSING:
        base["diagnoses"] = diagnoses
    if rejections is not MISSING:
        base["guard_rejections"] = rejections
    base.update(fields)
    return base


def d3(r, scope=None):
    return v2.d3_v2(r, scope or SCOPE, normalize)


def facts_v1(r):
    return v1.extract_facts(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None).evidence


# ============================================================================= edit_symbol fixtures (E1-E7)
def test_e1_rejected_edit_then_read_then_admitted_edit_is_unknown():
    """Per-call edit admission is not persisted, so the read between the bounds cannot be resolved."""
    r = row([edit(1), read(2), edit(3, success=True)], [view(2)], rejections=[rejection(tool="edit_symbol", reason="unread_edit")])
    assert d3(r) is U
    assert facts_v1(r) is F


def test_e2_rejected_edit_no_read_then_admitted_edit_is_false():
    r = row([edit(1), edit(3, success=True)], [], rejections=[rejection(tool="edit_symbol", reason="unread_edit")])
    assert d3(r) is F


def test_e3_admitted_but_failed_edit_after_complete_read_is_true():
    r = row([read(1), edit(2)], [view(1)])
    assert d3(r) is T


def test_e4_successful_edit_after_complete_read_is_true():
    r = row([read(1), edit(2, success=True)], [view(1)])
    assert d3(r) is T


def test_e5_mixed_failed_edits_with_one_rejection_is_unknown():
    """Aggregate counts must not identify which of the two failed calls was rejected."""
    r = row([edit(1), read(2), edit(3)], [view(2)], rejections=[rejection(tool="edit_symbol", reason="unread_edit")])
    assert d3(r) is U


def test_e6_missing_or_malformed_guard_log_does_not_invent_admission():
    absent = row([read(1), edit(2)], [view(1)])
    assert "guard_rejections" not in absent  # genuinely missing telemetry, not an empty list
    assert d3(absent) is T
    for rejections in ([], None, [{"tool": "edit_symbol"}], "not-a-list", [None]):
        r = row([read(1), edit(2)], [view(1)], rejections=rejections)
        assert d3(r) is T, rejections
    # and with the read after the attempt the same evidence gap gives UNKNOWN, never an invented TRUE/FALSE
    r = row([edit(1), read(2)], [view(2)], rejections=[rejection(tool="edit_symbol")])
    assert d3(r) is U


def test_e7_repeat_blocked_edit_after_successful_edit():
    blocked = edit(3)
    blocked["result_head"] = '{"error": "Duplicate failed call detected: edit_symbol with same arguments."}'
    r = row([edit(1, success=True), read(2), blocked], [view(2)])
    assert d3(r) is F  # the cutoff is the successful round-1 edit; the later read does not count


# ============================================================================= diagnose fixtures (D1-D6)
def test_d1_refused_diagnosis_then_read_then_admitted_diagnosis_is_true():
    """The motivating case: v1 says FALSE, v2 says TRUE."""
    r = row([diag(1), read(2), diag(3)], [view(2)],
            diagnoses=[record(refused="evidence_requires_read"), record()], rejections=[rejection()])
    assert d3(r) is T
    assert facts_v1(r) is F


def test_d2_refused_diagnosis_without_evidence_is_false():
    r = row([diag(1)], [], diagnoses=[record(refused="evidence_requires_read")], rejections=[rejection()])
    assert d3(r) is F


def test_d3_admitted_diagnosis_after_complete_read_is_true():
    r = row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()])
    assert d3(r) is T


def test_d4_successful_diagnosis_before_any_read_is_false():
    r = row([diag(1, success=True), read(3)], [view(3)], diagnoses=[record()])
    assert d3(r) is F


def test_d5_retry_shape_two_records_for_one_call_is_unknown():
    """A recovery retry of a rejected diagnose emits a second guard.rejected: the stream no longer aligns."""
    r = row([diag(1), read(2)], [view(2)],
            diagnoses=[record(refused="evidence_requires_read"), record(refused="evidence_requires_read")],
            rejections=[rejection(), rejection()])
    assert d3(r) is U


def test_d6_path_misalignment_is_unknown():
    r = row([diag(1), read(2)], [view(2)],
            diagnoses=[record(refused="evidence_requires_read", path=OTHER)], rejections=[rejection()])
    assert d3(r) is U


def test_guard_count_mismatch_degrades_to_unknown():
    """Precondition 4: refused records without matching diagnose rejections are not trusted."""
    r = row([diag(1), read(2)], [view(2)], diagnoses=[record(refused="evidence_requires_read")], rejections=[])
    assert d3(r) is U


def test_refused_is_never_inferred_from_result_text():
    head = '{"error": "Not recorded: mathlib/operations.py has not been read in this task"}'
    call = diag(1)
    call["result_head"] = head
    r = row([call, read(2)], [view(2)], diagnoses=[record()], rejections=[])
    assert d3(r) is U  # admission UNKNOWN: the text is not evidence


# ============================================================================= structural fixtures
@pytest.mark.parametrize("refused", [7, False, ["evidence_requires_read"], {}])
def test_non_string_refused_field_is_not_a_refusal(refused):
    """A `refused` value of an unexpected type establishes nothing, even when the rejection count happens to agree."""
    rejections = [rejection()] if refused else []
    r = row([diag(1), read(2)], [view(2)], diagnoses=[record(refused=refused)], rejections=rejections)
    assert v2.diagnose_admissions(r, normalize) is None
    assert d3(r) is U


def test_s1_calls_not_a_list_is_unknown():
    assert d3(row("not-a-list", [view(1)])) is U


def test_s1b_malformed_call_entry_collapses_the_lower_bound():
    r = row([read(1), "malformed", edit(2)], [view(1)])
    assert d3(r) is U  # the unreadable entry could have been an earlier attempt


def test_s2_no_attempt_matches_v1():
    with_read = row([read(1)], [view(1)])
    without = row([read(1)], [view(1, complete=False)])
    assert d3(with_read) is T and facts_v1(with_read) is T
    assert d3(without) is F and facts_v1(without) is F


def test_s3_multiple_gold_files_aggregate_with_tri_and():
    r = row([diag(1), read(2), diag(3), diag(1, path=OTHER)], [view(2)],
            diagnoses=[record(refused="evidence_requires_read"), record(), record(refused="evidence_requires_read", path=OTHER)],
            rejections=[rejection(), rejection(path=OTHER)])
    assert v2.d3_file(r, OPS, normalize) is T
    assert v2.d3_file(r, OTHER, normalize) is F
    assert d3(r, [OPS, OTHER]) is F


def test_s4_same_round_read_counts_for_that_round():
    r = row([diag(2, success=True), read(2)], [view(2)], diagnoses=[record()])
    assert d3(r) is T and facts_v1(r) is T


def test_s4b_malformed_view_is_unknown_not_false():
    r = row([read(1), diag(2, success=True)], [{"path": OPS, "complete": True}], diagnoses=[record()])
    assert d3(r) is U


def test_s4c_incomplete_view_only_is_false():
    r = row([read(1), diag(2, success=True)], [view(1, complete=False)], diagnoses=[record()])
    assert d3(r) is F


def test_s4d_unknown_completeness_view_is_unknown():
    r = row([read(1), diag(2, success=True)], [view(1, complete=None)], diagnoses=[record()])
    assert d3(r) is U


def test_non_integer_round_attempt_collapses_the_lower_bound():
    call = diag(1, success=True)
    call["round"] = "two"
    r = row([call, read(2)], [view(2)], diagnoses=[record()])
    assert d3(r) is U


def test_recorded_call_order_sets_the_bounds_not_the_smallest_round():
    """v1 takes the first attempt in recorded `calls` order (furthest_bottleneck.py:857-861, `setdefault`). v2 keeps
    that and changes only which actions qualify; taking the smallest numeric round would be a second, unauthorized
    factor. Contract-valid rows only — decreasing rounds are refused by D3_CALL_POSITION_CONTRACT."""
    r = row([read(1), diag(2, success=True), diag(3, success=True)], [view(1)], diagnoses=[record(), record()])
    assert v2.cutoff_bounds(r, OPS, normalize) == (2, 2)
    assert d3(r) is T
    later = row([read(4), diag(2, success=True), diag(3, success=True)], [view(4)], diagnoses=[record(), record()])
    assert v2.cutoff_bounds(later, OPS, normalize) == (2, 2)
    assert d3(later) is F and facts_v1(later) is F


# ============================================================================= Layer 0: producer envelope
def envelope(r):
    return v2.producer_envelope_violations(r)


def entry(r, task=DIV):
    return v2.extract_facts_v2(r, task, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)


def relevant(round_value=1, **extra):
    call = {"round": round_value, "tool": "diagnose", "success": True, "result_head": "", "args": {"path": OPS}}
    call.update(extra)
    return call


ENVELOPE_INVALID_ROWS = {
    "calls_key_missing": {"read_views": [view(1)]},
    "calls_none": row(None, [view(1)]),
    "calls_string": row("nope", [view(1)]),
    "calls_dict": row({"0": relevant()}, [view(1)]),
    "non_dict_entry_string": row([relevant(), "junk"], [view(1)]),
    "non_dict_entry_int": row([relevant(), 42], [view(1)]),
    "non_dict_entry_none": row([relevant(), None], [view(1)]),
    # truthy non-dicts
    "args_list": row([relevant(args=[OPS])], [view(1)]),
    "args_string": row([relevant(args=OPS)], [view(1)]),
    "args_int": row([relevant(args=7)], [view(1)]),
    "args_bool_true": row([relevant(args=True)], [view(1)]),
    # falsy non-dicts: `(args or {}).get(...)` does NOT raise on these, and they are rejected anyway — Layer 0
    # defines the admitted producer-envelope shape, not the set of values one current accessor happens to survive.
    "args_empty_list": row([relevant(args=[])], [view(1)]),
    "args_empty_string": row([relevant(args="")], [view(1)]),
    "args_zero": row([relevant(args=0)], [view(1)]),
    "args_bool_false": row([relevant(args=False)], [view(1)]),
}

#: name -> (row, expected D3 on that row) — exact values, so an accepted row with a wrong D3 fails here.
ENVELOPE_VALID_ROWS = {
    # No `args.path` in these four, so the call is not a relevant call, the cutoff is unbounded, and the complete
    # view at round 1 counts: TRUE. (Acceptance is the point; the exact value is asserted so a wrong one fails.)
    "empty_calls": (row([], [view(1)]), T),
    "args_absent": (row([{"round": 1, "tool": "diagnose", "success": True, "result_head": ""}], [view(1)]), T),
    "args_none": (row([relevant(args=None)], [view(1)]), T),
    "args_empty_dict": (row([relevant(args={})], [view(1)]), T),
    "valid_irrelevant_call": (row([read(1), {"round": 1, "tool": "list_directory", "success": True, "args": {"path": "."}}], [view(1)]), T),
    "valid_relevant_call": (row([read(1), relevant(2)], [view(1)], diagnoses=[record()], rejections=[]), T),
    "no_call_row": (row([read(1)], [view(1)]), T),
    # the producer legitimately summarizes a long string argument into {chars, sha256, head} (repo_task_eval.py:193)
    "summarized_path_dict": (row([relevant(args={"path": {"chars": 400, "sha256": "ab", "head": "x"}})], [view(1)]), T),
}


@pytest.mark.parametrize("name", sorted(ENVELOPE_INVALID_ROWS))
def test_envelope_invalid_rows_are_refused_at_the_supported_entry(name):
    r = dict(ENVELOPE_INVALID_ROWS[name], condition="qwen_selectorkind")
    assert envelope(r), name
    with pytest.raises(v2.RowEnvelopeViolation) as caught:
        v2.check_producer_envelope(r)
    assert caught.value.contract == "D3_PRODUCER_ENVELOPE_CONTRACT"
    with pytest.raises(v2.RowEnvelopeViolation):
        entry(r)
    with pytest.raises(v2.RowEnvelopeViolation):
        v2.classify_row_v2(r, DIV, StubReplayer())
    assert isinstance(caught.value, v2.RowContractViolation)   # existing handlers keep working


@pytest.mark.parametrize("name", sorted(ENVELOPE_VALID_ROWS))
def test_envelope_valid_rows_are_accepted(name):
    """Minimality: a present-and-non-null `args` must be a dict; absent and None are allowed even though the current
    producer always writes a dict, because methodology safety does not depend on rejecting them. Each fixture asserts
    its exact D3 value, so an accepted row that classifies wrongly fails here."""
    base, expected = ENVELOPE_VALID_ROWS[name]
    r = dict(base, condition="qwen_selectorkind")
    assert envelope(r) == [], name
    v2.check_producer_envelope(r)          # must not raise
    facts, _descriptive = entry(r)         # and the row classifies to the expected value
    assert facts.evidence is expected, name


def test_the_args_boundary_is_exactly_present_non_null_non_dict():
    """One place where both sides of the boundary sit together, so a change to either direction is visible."""
    def envelope_of(value, present=True):
        call = {"round": 1, "tool": "diagnose", "success": True}
        if present:
            call["args"] = value
        return v2.producer_envelope_violations({"calls": [call]})

    assert envelope_of(None, present=False) == []          # absent
    for accepted in (None, {}, {"path": OPS}):
        assert envelope_of(accepted) == [], accepted
    for rejected in ([], "", 0, False, ["x"], "x", 7, True, 2.5, set()):
        assert envelope_of(rejected), rejected


def test_envelope_is_not_a_general_schema_validator():
    """Deliberately NOT required by Layer 0: tool type, success type, path type, result fields, or any other row key."""
    odd = row([{"round": 1, "tool": 7, "success": "yes", "args": {"path": 42}}], [view(1)])
    odd.pop("diagnoses", None)
    odd.pop("guard_rejections", None)
    odd.pop("read_views", None)
    assert envelope(odd) == []


# ============================================================================= validation precedence (Layer 0 -> 1 -> v1)
def test_precedence_case_a_envelope_wins_over_position_violation():
    """Both layers violated: Layer 0 must be the reported error, never Layer 1."""
    r = row([relevant(5), unpositioned(diag(2), "two"), "junk"], [view(1)],
            diagnoses=[record(), record()], rejections=[], condition="qwen_selectorkind")
    assert envelope(r) and violations(r)                 # genuinely invalid at both layers
    with pytest.raises(v2.RowEnvelopeViolation) as caught:
        entry(r)
    assert caught.value.contract == "D3_PRODUCER_ENVELOPE_CONTRACT"


def test_precedence_case_b_position_violation_when_envelope_is_clean():
    r = row([diag(5, success=True), diag(2, success=True)], [view(1)],
            diagnoses=[record(), record()], rejections=[], condition="qwen_selectorkind")
    assert envelope(r) == [] and violations(r)
    with pytest.raises(v2.RowContractViolation) as caught:
        entry(r)
    assert caught.value.contract == "D3_CALL_POSITION_CONTRACT"
    assert not isinstance(caught.value, v2.RowEnvelopeViolation)


def test_precedence_case_c_valid_row_reaches_frozen_v1():
    r = row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()], rejections=[],
            condition="qwen_selectorkind")
    assert envelope(r) == [] and violations(r) == []
    facts, _descriptive = entry(r)
    base = v1.extract_facts(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    assert facts.evidence is T and dataclasses.replace(base, evidence=T) == facts


@pytest.mark.parametrize("name", sorted(ENVELOPE_INVALID_ROWS))
def test_envelope_invalid_row_never_reaches_frozen_v1(name, monkeypatch):
    """Order of effects, not just the exception type: frozen v1's extractor must not be entered at all."""
    called = []
    monkeypatch.setattr(v1, "extract_facts", lambda *a, **k: called.append(a) or (_ for _ in ()).throw(AssertionError("v1 reached")))
    with pytest.raises(v2.RowEnvelopeViolation):
        entry(dict(ENVELOPE_INVALID_ROWS[name], condition="qwen_selectorkind"))
    assert called == [], name


def test_position_invalid_row_never_reaches_frozen_v1(monkeypatch):
    called = []
    monkeypatch.setattr(v1, "extract_facts", lambda *a, **k: called.append(a))
    r = row([diag(5, success=True), diag(2, success=True)], [view(1)], diagnoses=[record(), record()], rejections=[])
    with pytest.raises(v2.RowContractViolation):
        entry(r)
    assert called == []


# ============================================================================= D3_CALL_POSITION_CONTRACT
def violations(r, scope=None):
    return v2.call_position_violations(r, scope or SCOPE, normalize)


def unpositioned(call, value=..., drop=False):
    """A relevant call with a bad or absent round — producer-impossible, so a contract violation."""
    if drop:
        call.pop("round", None)
    else:
        call["round"] = value
    return call


# (calls, diagnoses, rejections, expected D3) — each row exercises a distinct admission state.
VALID_ROWS = {
    "refused_then_admitted_diagnosis": ([read(1), diag(2), diag(3)],
                                        [record(refused="evidence_requires_read"), record()], [rejection()], T),
    "successful_diagnosis_at_view_round": ([diag(1, success=True), read(2)], [record()], [], T),
    "successful_diagnosis_after_read": ([read(1), diag(2, success=True)], [record()], [], T),
    "failed_diagnosis_admission_unknown": ([read(1), diag(2)], [record()], [], T),
    "successful_edit": ([read(1), edit(2, success=True)], [], [], T),
    "failed_edit_admission_unknown": ([read(1), edit(2)], [], [], T),
    "failed_edit_at_view_round": ([edit(1), read(2)], [], [], T),
    "no_relevant_attempt": ([read(1), read(2)], [], [], T),
    "equal_rounds_two_calls": ([read(1), diag(2, success=True), edit(2)], [record()], [], T),
    "round_zero_before_the_view": ([diag(0, success=True), read(0)], [record()], [], F),
    "irrelevant_decrease_other_tool": ([read(5), diag(2, success=True), read(1)], [record()], [], T),
    "irrelevant_decrease_other_path": ([read(1), diag(4, path=OTHER_NON_GOLD), diag(2, success=True)],
                                       [record(path=OTHER_NON_GOLD), record()], [], T),
}


@pytest.mark.parametrize("name", sorted(VALID_ROWS))
def test_contract_valid_rows_are_accepted_and_classified(name):
    calls, diagnoses, rejections, expected = VALID_ROWS[name]
    r = row(calls, [view(1)], diagnoses=diagnoses, rejections=rejections)
    assert violations(r) == []
    v2.check_call_positions(r, SCOPE, normalize)  # must not raise
    assert d3(r) is expected, name                # and the ordinary value is the expected one


def test_valid_rows_cover_every_admission_state():
    """The fixtures above must actually exercise TRUE, FALSE and UNKNOWN admission, not just parse."""
    seen = set()
    for calls, diagnoses, rejections, _expected in VALID_ROWS.values():
        r = row(calls, [view(1)], diagnoses=diagnoses, rejections=rejections)
        seen.update(value for _call, value in v2.attempt_admissions(r, normalize))
    assert seen == {T, F, U}


INVALID_ROWS = {
    # ordering violations
    "counterexample_b": [read(1), diag(4), diag(2, success=True)],
    "single_decrease": [read(1), diag(3), diag(2)],
    "multiple_decreases": [read(1), diag(5), diag(4), diag(3)],
    "decrease_between_edits": [read(1), edit(6), edit(2)],
    "decrease_across_tools": [read(1), edit(6), diag(2)],
    # position violations (relevant call the producer could not have emitted)
    "diagnosis_round_string": [read(1), unpositioned(diag(2), "two")],
    "diagnosis_round_missing": [read(1), unpositioned(diag(2), drop=True)],
    "diagnosis_round_true": [read(1), unpositioned(diag(2), True)],
    "diagnosis_round_false": [read(1), unpositioned(diag(2), False)],
    "diagnosis_round_float": [read(1), unpositioned(diag(2), 2.0)],
    "diagnosis_round_none": [read(1), unpositioned(diag(2), None)],
    "edit_round_string": [read(1), unpositioned(edit(2), "two")],
    "edit_round_missing": [read(1), unpositioned(edit(2), drop=True)],
    "edit_round_true": [read(1), unpositioned(edit(2), True)],
}


@pytest.mark.parametrize("name", sorted(INVALID_ROWS))
def test_contract_violating_rows_are_refused(name):
    calls = INVALID_ROWS[name]
    r = row(calls, [view(3)], diagnoses=[record() for c in calls if c["tool"] == "diagnose"], rejections=[])
    assert violations(r), name
    with pytest.raises(v2.RowContractViolation) as caught:
        v2.check_call_positions(r, SCOPE, normalize)
    assert caught.value.contract == "D3_CALL_POSITION_CONTRACT"


def test_counterexample_b_cannot_reach_classification():
    """The row that broke `v1 TRUE implies v2 TRUE` is producer-impossible. It must be refused, never classified:
    not FALSE, not UNKNOWN, not a label. Retained as the adversarial guard on the methodology domain."""
    r = row([read(1), diag(4), diag(2, success=True)], [view(3)],
            diagnoses=[record(refused="evidence_requires_read"), record()], rejections=[rejection()],
            condition="qwen_selectorkind")
    assert facts_v1(r) is T  # v1, frozen, still answers TRUE on this row
    with pytest.raises(v2.RowContractViolation):
        v2.extract_facts_v2(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    with pytest.raises(v2.RowContractViolation):
        v2.classify_row_v2(r, DIV, StubReplayer())


def test_validity_is_checked_before_any_extraction_work():
    """Ordering of effects, not just the final exception: this row both violates the contract and contains a non-dict
    call entry, which makes frozen v1's own extractor raise AttributeError. Checking validity first yields
    RowContractViolation; checking it afterwards would surface v1's crash instead."""
    r = row([read(1), "malformed", diag(5), diag(2)], [view(1)],
            diagnoses=[record(), record()], rejections=[], condition="qwen_selectorkind")
    with pytest.raises(AttributeError):
        v1.extract_facts(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    with pytest.raises(v2.RowContractViolation):
        v2.extract_facts_v2(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)


def test_cutoff_bounds_uses_recorded_order_below_the_validity_layer():
    """`cutoff_bounds` is a unit with its own documented semantics: first qualifying call in recorded order. On
    contract-valid rows that always equals the smallest round, so the distinction is only observable off-domain —
    exercised here directly, below the validity check that refuses such a row at the extraction layer."""
    off_domain = row([read(3), diag(5, success=True), diag(1, success=True)], [view(3)],
                     diagnoses=[record(), record()])
    assert violations(off_domain)  # the row is refused by extract_facts_v2; the unit is tested directly
    assert v2.cutoff_bounds(off_domain, OPS, normalize) == (5, 5)
    failed = row([read(3), diag(5), diag(1)], [view(3)], diagnoses=[record(), record()])
    assert v2.cutoff_bounds(failed, OPS, normalize) == (5, float("inf"))


def test_ordering_is_row_level_across_the_whole_gold_file_domain():
    """The producer invariant is global call ordering: a decrease between calls on DIFFERENT gold files violates the
    contract, even though each file has only one call and each file's own subsequence is trivially monotone."""
    r = row([read(1), diag(4, path=OPS), diag(2, path=OTHER)], [view(1)], diagnoses=[record(), record(path=OTHER)])
    assert violations(r, [OPS, OTHER])
    with pytest.raises(v2.RowContractViolation):
        v2.check_call_positions(r, [OPS, OTHER], normalize)
    # restarting the comparison per file would see two monotone one-element sequences and wrongly accept the row
    assert violations(r, [OPS]) == [] and violations(r, [OTHER]) == []


@pytest.mark.parametrize("bad_round", [True, False])
def test_bool_rounds_are_structural_violations_not_positions(bad_round):
    """`bool` subclasses `int`, so `isinstance(True, int)` is true — but `type(True) is int` is false and `call_log`
    writes plain ints, so a bool round is producer-impossible and refused, never read as round 1 or 0."""
    call = diag(2)
    call["round"] = bad_round
    assert v2.positioned_round(call) is None
    r = row([read(1), call, diag(3)], [view(1)], diagnoses=[record(), record()], condition="qwen_selectorkind")
    assert violations(r)
    with pytest.raises(v2.RowContractViolation):
        v2.extract_facts_v2(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)


def test_unpositioned_relevant_calls_are_refused_at_the_entry_point():
    """The three counterexamples that broke `v1 TRUE implies v2 TRUE` under the narrower contract. v1 answers TRUE on
    the first two; v2 must now refuse the row rather than return any value at all."""
    for label, call in [("string", unpositioned(diag(2, success=True), "two")),
                        ("missing", unpositioned(diag(2, success=True), drop=True)),
                        ("bool", unpositioned(diag(2, success=True), True))]:
        r = row([call, read(2)], [view(2)], diagnoses=[record()], rejections=[], condition="qwen_selectorkind")
        assert violations(r), label
        with pytest.raises(v2.RowContractViolation):
            v2.extract_facts_v2(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
        with pytest.raises(v2.RowContractViolation):
            v2.classify_row_v2(r, DIV, StubReplayer())


def test_unpositioned_admitted_call_keeps_unknown_below_the_entry_point():
    """Helper-level protection: `cutoff_bounds` must keep BOTH bounds open when an admitted relevant call has no
    usable position. Dropping the `unpositioned_admitted` branch would give (-inf, 5) here and collapse UNKNOWN to a
    determined FALSE. The row is refused at the entry point, but the helper's conservative behaviour still has to hold
    when it is called directly."""
    bad = unpositioned(diag(2, success=True), "x")
    r = row([bad, diag(5, success=True)], [view(9)], diagnoses=[record(), record()], rejections=[])
    assert violations(r)                                        # off-domain by construction
    assert v2.cutoff_bounds(r, OPS, normalize) == (v2.UNPOSITIONED, v2.UNBOUNDED)
    assert v2.d3_file(r, OPS, normalize) is U                   # UNKNOWN, not FALSE
    assert d3(r) is U
    # Kill path, stated explicitly: since the UNPOSITIONED repair, d3_file returns UNKNOWN for ANY row whose lower
    # bound is unpositioned, so dropping `unpositioned_admitted` is no longer observable in the D3 value — the mutant
    # would compute (UNPOSITIONED, 5) and still answer UNKNOWN. The bounds assertion above is therefore the only
    # discriminator, and it is deliberate: the helper must keep tracking that an admitted action exists at an unknown
    # position, so a future change to the decision layer cannot silently resurrect the determined FALSE.
    assert v2.view_value(r["read_views"], OPS, 5) is F           # what the mutant's upper bound would compare
    assert v2.view_value(r["read_views"], OPS, v2.UNPOSITIONED) is F
    mutant_answer = v2.view_value(r["read_views"], OPS, v2.UNPOSITIONED)
    assert mutant_answer is F and v2.d3_file(r, OPS, normalize) is U  # agreement at the view layer, UNKNOWN at D3


def test_round_zero_is_a_valid_position():
    """A call emitted before the first turn.round is persisted at round 0 and must participate normally."""
    call = diag(0, success=True)
    assert v2.positioned_round(call) == 0
    r = row([read(0), call], [view(0)], diagnoses=[record()])
    assert violations(r) == []
    assert v2.cutoff_bounds(r, OPS, normalize) == (0, 0)
    assert d3(r) is T
    without_read = row([call], [view(2)], diagnoses=[record()])
    assert v2.cutoff_bounds(without_read, OPS, normalize) == (0, 0)
    assert d3(without_read) is F


#: Envelope-INVALID rows that are ALSO used to check helper conservatism. Layer 0 refuses every one at the supported
#: entry; Layer 1 is separately silent on them because relevance is undecidable there. Three tests assert those facts
#: apart, so nothing here can be read as "this row is acceptable methodology input".
ENVELOPE_INVALID_HELPER_ROWS = {
    "calls_missing": row([], [view(1)]) | {"calls": None},
    "calls_not_a_list": row("nope", [view(1)]),
    "non_dict_call_entry": row([read(1), "malformed", diag(2)], [view(1)]),
    "non_dict_entry_only": row([read(1), "malformed"], [view(1)]),
}


ADMITTED_R3 = {"round": 3, "tool": "edit_symbol", "success": True, "result_head": "",
               "args": {"path": OPS, "selector_kind": "python_symbol", "target": "divide", "replacement": "x"}}

#: Malformed-telemetry shapes. Each is INVALID methodology input (Layer 0 refuses it at the supported entry) AND is
#: separately used to check that the lower-level helpers stay conservative when called directly. The two facts are
#: asserted by two different tests on purpose: helper conservatism is defence-in-depth and never implies validity.
HELPER_CONSERVATISM_ROWS = {
    "A_no_views": (["junk", ADMITTED_R3], []),
    "B_incomplete_view_before": (["junk", ADMITTED_R3], [view(1, complete=False)]),
    "C_complete_view_above_lmax": (["junk", ADMITTED_R3], [view(50)]),          # reproduced the unsound FALSE
    "D_no_later_relevant_call": (["junk", read(2)], [view(1, complete=False)]),
    "E_malformed_entries_around_valid_calls": ([diag(1, success=True), "junk", 42, diag(4, success=True)],
                                               [view(2, complete=False)]),
    "F_calls_not_a_list": ("nope", [view(50)]),
    "G_calls_none": (None, [view(50)]),
}


def _helper_row(name):
    calls, views = HELPER_CONSERVATISM_ROWS[name]
    diagnoses = [record() for c in (calls if isinstance(calls, list) else [])
                 if isinstance(c, dict) and c.get("tool") == "diagnose"]
    return row(calls, views, diagnoses=diagnoses, rejections=[])


@pytest.mark.parametrize("name", sorted(HELPER_CONSERVATISM_ROWS))
def test_helper_stays_conservative_on_malformed_telemetry(name):
    """Layer 3 defence-in-depth: called directly, the helpers must report an unpositionable lower cutoff and answer
    UNKNOWN — never a determined value. The entry could have been the admitted action at any round, including after
    every recorded view; before the UNPOSITIONED rule, C returned a determined FALSE with a complete view at r50."""
    r = _helper_row(name)
    assert v2.cutoff_bounds(r, OPS, normalize)[0] == v2.UNPOSITIONED, name
    assert v2.d3_file(r, OPS, normalize) is U, name
    assert d3(r) is U, name


@pytest.mark.parametrize("name", sorted(HELPER_CONSERVATISM_ROWS))
def test_the_same_rows_are_invalid_methodology_input(name):
    """The other half of the separation: conservative helper behaviour does NOT make these rows acceptable. Every one
    violates the producer envelope and is refused at the supported entry point."""
    r = dict(_helper_row(name), condition="qwen_selectorkind")
    assert envelope(r), name
    with pytest.raises(v2.RowEnvelopeViolation):
        entry(r)


def test_truthy_non_dict_args_is_refused_at_entry_and_may_raise_in_helpers():
    """Documented honestly rather than given speculative semantics: Layer 0 refuses it; a direct helper call raises."""
    r = row([relevant(args=[OPS])], [view(1)], condition="qwen_selectorkind")
    assert envelope(r)
    with pytest.raises(v2.RowEnvelopeViolation):
        entry(r)
    with pytest.raises(AttributeError):
        v2.call_position_violations(r, SCOPE, normalize)


@pytest.mark.parametrize("value", [[], "", 0, False])
def test_falsy_non_dict_args_is_refused_although_the_helper_tolerates_it(value):
    """The distinguishing case for the Layer-0 boundary. `(args or {}).get(...)` does NOT raise on these, so a
    contract written as `if args and not isinstance(args, dict)` would accept them — Layer 0 rejects them anyway,
    because it defines the admitted producer-envelope shape, not what one current accessor survives."""
    call = relevant(args=value)
    assert (call.get("args") or {}).get("path") is None      # the helper genuinely tolerates it
    r = row([call], [view(1)], condition="qwen_selectorkind")
    assert envelope(r), value
    with pytest.raises(v2.RowEnvelopeViolation) as caught:
        entry(r)
    assert caught.value.contract == "D3_PRODUCER_ENVELOPE_CONTRACT"
    assert isinstance(caught.value, v2.RowContractViolation)
    with pytest.raises(v2.RowEnvelopeViolation):
        v2.classify_row_v2(r, DIV, StubReplayer())


def test_descriptive_normalization_is_independent_of_the_normative_cutoff():
    """Finding 11, option B: `descriptive_facts` inspects the malformed-telemetry condition independently of
    `cutoff_bounds` on purpose. This pins the direction of the independence — a descriptive result may differ while
    the normative D3 value is untouched — so a later refinement of the descriptive notion cannot move the cutoff."""
    r = row([read(1), "malformed", diag(2, success=True)], [view(1)], diagnoses=[record()], rejections=[])
    assert v2.cutoff_bounds(r, OPS, normalize)[0] is v2.UNPOSITIONED
    assert v2.d3_file(r, OPS, normalize) is U and d3(r) is U          # normative side
    assert v2.descriptive_facts(r, SCOPE, normalize)["D3_ATTEMPT_OBSERVED"] == "UNKNOWN"   # descriptive side

    # Direction of the independence: a row where the descriptive predicate is the ONLY thing that can differ still
    # has an untouched normative D3. Asserted behaviourally — no source introspection, which would make this test
    # fire on any line-shifting mutation rather than on a real coupling.
    positioned = row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()], rejections=[])
    assert v2.d3_file(positioned, OPS, normalize) is T
    assert v2.descriptive_facts(positioned, SCOPE, normalize)["D3_ATTEMPT_OBSERVED"] == "TRUE"


def test_ordinary_false_is_not_collapsed_into_unknown():
    """The repair must not turn every FALSE into UNKNOWN: a fully positioned row with no evidence before the cutoff
    still answers FALSE."""
    r = row([diag(2, success=True), read(5)], [view(5)], diagnoses=[record()], rejections=[])
    assert violations(r) == []
    assert v2.cutoff_bounds(r, OPS, normalize) == (2, 2)
    assert d3(r) is F and facts_v1(r) is F


def test_view_value_itself_is_unchanged_at_the_sentinel():
    """The repair lives in `d3_file`, not in `view_value`: inherited v1 view semantics are untouched, so evaluating
    views at the sentinel still reports FALSE — which is exactly why the decision layer must not use it."""
    assert v2.view_value([view(50)], OPS, v2.UNPOSITIONED) is F
    assert v2.view_value([view(50)], OPS, 60) is T


@pytest.mark.parametrize("name", sorted(ENVELOPE_INVALID_HELPER_ROWS))
def test_these_malformed_rows_are_refused_at_the_supported_entry(name):
    """Stated first: Layer 0 is the layer that rejects them, so neither test below can read as acceptance."""
    r = dict(ENVELOPE_INVALID_HELPER_ROWS[name], condition="qwen_selectorkind")
    assert envelope(r), name
    with pytest.raises(v2.RowEnvelopeViolation):
        entry(r)


@pytest.mark.parametrize("name", sorted(ENVELOPE_INVALID_HELPER_ROWS))
def test_layer_1_is_silent_on_them_because_relevance_is_undecidable(name):
    """Layer 1 covers relevant-call position and order, not row schema: a non-dict entry cannot be inspected to decide
    relevance, so the position contract reports nothing about it. That silence is not acceptance — Layer 0 already
    refused the row. (Frozen v1 raises AttributeError on these, so no comparison claim rests on them either.)"""
    r = ENVELOPE_INVALID_HELPER_ROWS[name]
    assert violations(r) == [], name
    v2.check_call_positions(r, SCOPE, normalize)  # must not raise


@pytest.mark.parametrize("name", sorted(ENVELOPE_INVALID_HELPER_ROWS))
def test_direct_helper_calls_on_them_stay_conservative(name):
    """Layer 3 defence-in-depth only: called directly, the helpers answer UNKNOWN, never a determined value."""
    assert d3(ENVELOPE_INVALID_HELPER_ROWS[name]) is U, name


def test_malformed_entry_does_not_hide_a_genuine_decrease():
    r = row([read(1), "malformed", diag(5), diag(2)], [view(1)], diagnoses=[record(), record()])
    assert violations(r)
    with pytest.raises(v2.RowContractViolation):
        v2.check_call_positions(r, SCOPE, normalize)


def test_attempt_paths_are_normalized_before_matching():
    """A './'-prefixed attempt is the same attempt; dropping normalization would hide it from the cutoff."""
    r = row([diag(1, success=True, path="./" + OPS), read(2)], [view(2)], diagnoses=[record(path="./" + OPS)])
    assert d3(r) is F


def test_s5_frozen_v1_artifacts_unchanged():
    for rel, sha in FROZEN_V1.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == sha, rel


# ============================================================================= admission unit rules
def test_p1_success_true_is_positive_admission():
    assert v2.call_admission(edit(1, success=True), U) is T
    assert v2.call_admission(diag(1, success=True), U) is T


@pytest.mark.parametrize("value", [1, "true", "True", [1], {"ok": 1}, 2.0])
def test_p1_requires_the_literal_true_not_truthiness(value):
    """P1 is normative: `success is True` marks the handler as having run. `call_log` writes `bool(...)`
    (repo_task_eval.py:246), so no producer row carries these, but a truthy non-bool must never be read as admission
    — the same discipline as `tri()` in frozen v1 (furthest_bottleneck.py:49-55)."""
    call = diag(1)
    call["success"] = value
    assert v2.call_admission(call, U) is U
    edit_call = edit(1)
    edit_call["success"] = value
    assert v2.call_admission(edit_call, U) is U


def test_p1_false_and_missing_success_are_not_admission():
    assert v2.call_admission(diag(1, success=False), U) is U
    no_success = {"round": 1, "tool": "diagnose", "args": {"path": OPS}, "result_head": ""}
    assert v2.call_admission(no_success, U) is U


def test_p1_truthiness_changes_the_cutoff_on_a_valid_row():
    """End-to-end discrimination for the rule above: reading `success=1` as admission would move Lmax to round 2 and
    turn this UNKNOWN into FALSE."""
    call = diag(2)
    call["success"] = 1
    r = row([call, read(3), diag(4, success=True)], [view(3)], diagnoses=[record(), record()], rejections=[])
    assert violations(r) == []
    assert v2.cutoff_bounds(r, OPS, normalize) == (2, 4)
    assert d3(r) is U


def test_p3_failed_edit_admission_is_always_unknown():
    assert v2.call_admission(edit(1), F) is U
    assert v2.call_admission(edit(1), T) is U


def test_p2_only_diagnose_can_be_positively_refused():
    assert v2.call_admission(diag(1), F) is F
    assert v2.call_admission(diag(1), U) is U


def test_diagnose_stream_preconditions():
    aligned = row([diag(1), diag(2)], [], diagnoses=[record(refused="evidence_requires_read"), record()], rejections=[rejection()])
    assert v2.diagnose_admissions(aligned, normalize) == [F, U]
    for broken in (
        row([diag(1)], [], diagnoses=[record(), record()], rejections=[]),
        row([diag(1)], [], diagnoses=[{"path": OPS}], rejections=[]),
        row([diag(1)], [], diagnoses=[{"path": OPS, "refused": 7}], rejections=[]),
        row([diag(1)], [], diagnoses=[record(refused="x")], rejections=[rejection(tool="edit_symbol")]),
        row([diag(1)], [], diagnoses=[record()], rejections="not-a-list"),
    ):
        assert v2.diagnose_admissions(broken, normalize) is None


# ============================================================================= descriptive facts
def test_descriptive_facts_distinguish_no_attempt_from_waiting():
    none_attempted = row([read(1)], [view(1)])
    assert v2.descriptive_facts(none_attempted, SCOPE, normalize) == {
        "D3_ATTEMPT_OBSERVED": "FALSE", "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT": "FALSE"}
    waited = row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()])
    assert v2.descriptive_facts(waited, SCOPE, normalize) == {
        "D3_ATTEMPT_OBSERVED": "TRUE", "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT": "FALSE"}


def test_descriptive_pre_evidence_attempt_is_true_for_refused_attempt():
    r = row([diag(1), read(2), diag(3)], [view(2)],
            diagnoses=[record(refused="evidence_requires_read"), record()], rejections=[rejection()])
    facts = v2.descriptive_facts(r, SCOPE, normalize)
    assert facts["D3_OBSERVED_PRE_EVIDENCE_ATTEMPT"] == "TRUE" and facts["D3_ATTEMPT_OBSERVED"] == "TRUE"
    assert d3(r) is T  # the descriptive fact and D3 disagree by design


def test_descriptive_facts_unknown_on_malformed_calls():
    assert v2.descriptive_facts(row([read(1), "bad"], [view(1)]), SCOPE, normalize) == {
        "D3_ATTEMPT_OBSERVED": "UNKNOWN", "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT": "UNKNOWN"}


def test_descriptive_facts_are_not_classify_inputs():
    """Counterfactual: two rows that differ in BOTH descriptive facts but produce identical TrajectoryFacts must
    classify identically. `classify` takes only TrajectoryFacts, and neither descriptive name is a field of it."""
    field_names = {f.name for f in dataclasses.fields(v1.TrajectoryFacts)}
    assert not {"d3_attempt_observed", "d3_observed_pre_evidence_attempt"} & field_names

    pre_evidence = row([diag(1), read(2), diag(3)], [view(2)],
                       diagnoses=[record(refused="evidence_requires_read"), record()], rejections=[rejection()],
                       condition="qwen_selectorkind")
    waited = row([read(2), diag(3)], [view(2)], diagnoses=[record()], rejections=[], condition="qwen_selectorkind")

    facts_a, desc_a = v2.extract_facts_v2(pre_evidence, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    facts_b, desc_b = v2.extract_facts_v2(waited, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    assert desc_a != desc_b                       # the descriptive facts genuinely differ
    assert facts_a == facts_b                     # the classifier's whole input does not
    assert v2.classify(facts_a).label == v2.classify(facts_b).label
    assert v2.classify(facts_a) == v2.classify(facts_b)


# ============================================================================= properties
def _insert_earlier_refused_diagnosis(r):
    """Add a positively guard-rejected diagnosis before everything, leaving admitted actions and views unchanged."""
    shifted = {**r, "calls": [diag(0)] + list(r["calls"]),
               "diagnoses": [record(refused="evidence_requires_read")] + list(r.get("diagnoses") or []),
               "guard_rejections": [rejection()] + list(r.get("guard_rejections") or [])}
    return shifted


PROPERTY_ROWS = [
    row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()]),
    row([read(1), diag(2)], [view(1)], diagnoses=[record()]),
    row([diag(2, success=True), read(3)], [view(3)], diagnoses=[record()]),
    row([diag(2, success=True)], [], diagnoses=[record()]),
    row([read(1), diag(2, success=True)], [view(1, complete=False)], diagnoses=[record()]),
    row([read(2), diag(2, success=True)], [view(2)], diagnoses=[record()]),
]


@pytest.mark.parametrize("base", PROPERTY_ROWS)
def test_property_earlier_refused_diagnosis_does_not_change_d3(base):
    assert d3(_insert_earlier_refused_diagnosis(base)) is d3(base)


def test_property_earlier_refused_diagnosis_may_change_the_descriptive_fact():
    base = row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()])
    before = v2.descriptive_facts(base, SCOPE, normalize)["D3_OBSERVED_PRE_EVIDENCE_ATTEMPT"]
    after = v2.descriptive_facts(_insert_earlier_refused_diagnosis(base), SCOPE, normalize)["D3_OBSERVED_PRE_EVIDENCE_ATTEMPT"]
    assert (before, after) == ("FALSE", "TRUE")


@pytest.mark.parametrize("base", PROPERTY_ROWS)
def test_property_earlier_failed_edit_moves_only_toward_unknown(base):
    """The edit observability gap may cost determinacy; it must never flip TRUE to FALSE or FALSE to TRUE."""
    before = d3(base)
    after = d3({**base, "calls": [edit(0)] + list(base["calls"])})
    assert after is before or after is U


# --- monotonicity over the synthetic state space, against v1's own implementation
def _all_state_space_candidates():
    """Attempt shapes x view placements, covering admission TRUE/FALSE/UNKNOWN, views before/at/between/after the
    bounds, malformed, unknown-completeness and absent views, the no-attempt case, and out-of-order rounds.
    Includes candidates outside the methodology domain; `_state_space_rows` filters those out."""
    attempt_shapes = {
        "none": ([], [], []),
        "out_of_order_failed_diagnoses": ([diag(4), diag(2)], [record(), record()], []),
        "out_of_order_successful_diagnoses": ([diag(4, success=True), diag(2, success=True)], [record(), record()], []),
        "out_of_order_refused_then_admitted": ([diag(4), diag(2, success=True)],
                                               [record(refused="evidence_requires_read"), record()], [rejection()]),
        "out_of_order_failed_edits": ([edit(4), edit(2)], [], []),
        "out_of_order_edit_then_earlier_success": ([edit(4), edit(2, success=True)], [], []),
        "unpositioned_string_round": ([unpositioned(diag(4, success=True), "two")], [record()], []),
        "unpositioned_missing_round": ([unpositioned(diag(4, success=True), drop=True)], [record()], []),
        "unpositioned_bool_round": ([unpositioned(diag(4, success=True), True)], [record()], []),
        "unpositioned_then_positioned": ([unpositioned(diag(2, success=True), "x"), diag(4, success=True)],
                                         [record(), record()], []),
        "refused_diagnose": ([diag(2)], [record(refused="evidence_requires_read")], [rejection()]),
        "refused_then_admitted_diagnose": ([diag(2), diag(4)], [record(refused="evidence_requires_read"), record()], [rejection()]),
        "admitted_failed_diagnose": ([diag(4)], [record()], []),
        "successful_diagnose": ([diag(4, success=True)], [record()], []),
        "failed_edit": ([edit(4)], [], []),
        "successful_edit": ([edit(4, success=True)], [], []),
        "failed_edit_then_successful_edit": ([edit(2), edit(4, success=True)], [], []),
    }
    view_shapes = {
        "none": [],
        "complete_r1": [view(1)],
        "complete_r3": [view(3)],
        "complete_r4": [view(4)],
        "complete_r5": [view(5)],
        "incomplete_r1": [view(1, complete=False)],
        "unknown_r1": [view(1, complete=None)],
        "malformed": [{"path": OPS, "complete": True}],
    }
    for (aname, (calls, diagnoses, rejections)), (vname, views) in itertools.product(attempt_shapes.items(), view_shapes.items()):
        yield f"{aname}|{vname}", row([read(1)] + list(calls), views, diagnoses=diagnoses, rejections=rejections)


#: Shapes whose rows are structurally invalid by construction — every view pairing of them must be refused.
INVALID_SHAPE_PREFIXES = ("out_of_order", "unpositioned")


def _partition_state_space():
    """Split the generated candidates into expected-valid and expected-invalid, by SHAPE rather than by asking the
    implementation. A contract change then breaks the population assertions instead of silently shrinking the
    theorem search."""
    valid, invalid = [], []
    for name, candidate in _all_state_space_candidates():
        target = invalid if name.startswith(INVALID_SHAPE_PREFIXES) else valid
        target.append((name, candidate))
    return valid, invalid


def _state_space_rows():
    """Only the expected-valid candidates: the theorem is stated over the methodology domain."""
    return _partition_state_space()[0]


def test_state_space_populations_are_exactly_as_expected():
    """Fail closed: the expected-valid and expected-invalid populations are asserted by exact count and by the
    implementation's agreement with the shape-based expectation. If the contract changes, this fails rather than
    quietly reducing the property search."""
    valid, invalid = _partition_state_space()
    assert (len(valid), len(invalid)) == (64, 72)   # 8 valid shapes and 9 invalid shapes, each across 8 view sets
    assert len(valid) + len(invalid) == len(list(_all_state_space_candidates()))
    for name, candidate in valid:
        assert v2.call_position_violations(candidate, SCOPE, normalize) == [], name
    for name, candidate in invalid:
        assert v2.call_position_violations(candidate, SCOPE, normalize), name


def test_every_adversarial_shape_is_refused():
    """Structural invariant, so asserted exactly: EVERY row of every adversarial shape the reviews produced —
    decreasing rounds and unpositioned relevant calls — must be refused, not classified. No threshold."""
    _valid, invalid = _partition_state_space()
    assert len(invalid) == 72
    for name, candidate in invalid:
        assert v2.call_position_violations(candidate, SCOPE, normalize), name
        with pytest.raises(v2.RowContractViolation):
            v2.check_call_positions(candidate, SCOPE, normalize)


@pytest.mark.parametrize("name,r", list(_state_space_rows()))
def test_monotonicity_v1_true_implies_v2_true(name, r):
    before, after = facts_v1(r), d3(r)
    if before is T:
        assert after is T, name
    if before is U:
        assert after in (U, T), name


@pytest.mark.parametrize("name,r", list(_state_space_rows()))
def test_only_the_evidence_field_differs_between_v1_and_v2(name, r):
    """v2 is single-factor: on every contract-valid row, each non-evidence TrajectoryFacts field is identical to
    frozen v1's. Compared field by field so a failure names the field that drifted; the companion mutation
    `extract_facts_v2_alters_a_non_evidence_field` proves this test detects such a change rather than restating the
    `replace(...)` call that produces the value."""
    base = v1.extract_facts(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    facts, _descriptive = v2.extract_facts_v2(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    differing = [f.name for f in dataclasses.fields(v1.TrajectoryFacts)
                 if f.name != "evidence" and getattr(base, f.name) != getattr(facts, f.name)]
    assert differing == [], f"{name}: non-evidence field(s) changed: {differing}"


def test_state_space_contains_every_transition_direction_claimed():
    seen = {(facts_v1(r), d3(r)) for _name, r in _state_space_rows()}
    assert (F, T) in seen and (F, F) in seen and (F, U) in seen and (T, T) in seen
    assert not any(b is T and a is not T for b, a in seen)
    assert not any(b is U and a is F for b, a in seen)


@pytest.mark.parametrize("first,second", list(itertools.product([T, F, U], repeat=2)))
def test_multi_file_d3_equals_tri_and_of_the_per_file_values(first, second):
    """v2's row-level aggregation is v1's `tri_and` over the per-file values, for every combination."""
    calls, diagnoses, views = [], [], []
    for path, value in ((OPS, first), (OTHER, second)):
        if value is T:
            calls += [read(1, path=path), diag(2, success=True, path=path)]
            views.append(view(1, path=path))
            diagnoses.append(record(path=path))
        elif value is F:
            calls += [diag(2, success=True, path=path)]
            views.append(view(1, path=path, complete=False))
            diagnoses.append(record(path=path))
        else:
            calls += [edit(1, path=path), read(2, path=path)]
            views.append(view(2, path=path))
    r = row(calls, views, diagnoses=diagnoses, rejections=[])
    assert v2.d3_file(r, OPS, normalize) is first
    assert v2.d3_file(r, OTHER, normalize) is second
    assert d3(r, [OPS, OTHER]) is v1.tri_and(first, second)


# ============================================================================= D3 gold-file domain equality with v1
JSON_TASK = TASKS_BY_NAME["config_add_feature"]
APP = normalize(JSON_TASK.gold_files[0])
OPS_SEED = (REPOS_DIR / DIV.repo / OPS).read_text(encoding="utf-8")
APP_SEED = (REPOS_DIR / JSON_TASK.repo / APP).read_text(encoding="utf-8")


def synthetic_task(repo, gold_files, reference_patch):
    return SimpleNamespace(name="synthetic", repo=repo, gold_files=tuple(gold_files), reference_patch=reference_patch)


DOMAIN_CASES = {
    # name: (task, whether v1 creates a regions/changed_json key for the gold file)
    "py_key_with_non_empty_region": (synthetic_task(DIV.repo, [OPS], {OPS: OPS_SEED.replace("return a / b", "return a / b if b else 0")}), True),
    "py_key_with_empty_region": (synthetic_task(DIV.repo, [OPS], {OPS: OPS_SEED}), True),
    "py_key_with_unparseable_reference": (synthetic_task(DIV.repo, [OPS], {OPS: "def ("}), True),
    "py_key_absent_from_reference_patch": (synthetic_task(DIV.repo, [OPS], {}), False),
    "py_reference_patch_none": (synthetic_task(DIV.repo, [OPS], None), False),
    "json_key_with_changed_locations": (synthetic_task(JSON_TASK.repo, [APP], {APP: APP_SEED.replace("{", '{"zz": 1,', 1)}), True),
    "json_key_with_no_changed_locations": (synthetic_task(JSON_TASK.repo, [APP], {APP: APP_SEED}), True),
    "json_key_with_unparseable_reference": (synthetic_task(JSON_TASK.repo, [APP], {APP: "{not json"}), True),
    "gold_file_missing_from_repo": (synthetic_task(DIV.repo, ["mathlib/nope.py"], {"mathlib/nope.py": "x = 1"}), False),
    "gold_file_neither_py_nor_json": (synthetic_task(DIV.repo, ["README.md"], {"README.md": "text"}), False),
}


@pytest.mark.parametrize("name", sorted(DOMAIN_CASES))
def test_v2_d3_file_domain_equals_v1(name):
    """The amendment may change admission and the cutoff; it may NOT change which gold files participate in D3.
    A domain difference shows up as v1 evidence determined while v2 evidence is UNKNOWN (empty scope), or vice versa."""
    task, in_domain = DOMAIN_CASES[name]
    gold = normalize(task.gold_files[0])
    r = row([read(1, path=gold), diag(2, success=True, path=gold)], [view(1, path=gold)], diagnoses=[record(path=gold)])
    scope = v2.d1_region_files(task, REPOS_DIR, defect_lines, normalize)
    assert scope == ([gold] if in_domain else []), name
    v1_value = v1.extract_facts(r, task, StubReplayer(), defect_lines, REPOS_DIR, normalize, None).evidence
    assert v2.d3_v2(r, scope, normalize) is v1_value, name


def test_empty_d3_domain_is_unknown_in_both_versions():
    """An empty gold-file domain is UNKNOWN in v1 (`tri_and(*per_file) if per_file else U`,
    furthest_bottleneck.py:882) and must be UNKNOWN in v2 by the explicit guard, not by accident of `tri_and([])` —
    which returns TRUE."""
    assert v1.tri_and() is T                     # the accident the guard must not rely on
    r = row([read(1), diag(2, success=True)], [view(1)], diagnoses=[record()])
    assert v2.d3_v2(r, [], normalize) is U
    task = synthetic_task(DIV.repo, ["README.md"], {"README.md": "text"})   # no .py/.json gold file
    assert v2.d1_region_files(task, REPOS_DIR, defect_lines, normalize) == []
    v1_value = v1.extract_facts(r, task, StubReplayer(), defect_lines, REPOS_DIR, normalize, None).evidence
    facts, _desc = v2.extract_facts_v2(r, task, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    assert v1_value is U and facts.evidence is U


def test_view_round_bool_follows_inherited_v1_semantics():
    """Deliberate asymmetry, pinned: the `type(...) is int` rule governs relevant CALL rounds only. View rounds keep
    frozen v1's `isinstance(..., int)` (furthest_bottleneck.py:871-872), under which a bool round acts as round 1."""
    bool_view = {"round": True, "path": OPS, "complete": True}
    assert v2.view_value([bool_view], OPS, 1) is T          # counts at cutoff 1
    assert v2.view_value([bool_view], OPS, 0) is F          # does not count at cutoff 0
    r = row([read(1), diag(2, success=True)], [bool_view], diagnoses=[record()])
    assert violations(r) == []                              # a view round is never a contract matter
    assert d3(r) is T and facts_v1(r) is T                  # and v1 agrees, which is the point of the inheritance


# ============================================================================= two real gold files, end to end
TWO_FILE_SEED_A = "def alpha(x):\n    return x + 0\n"
TWO_FILE_SEED_B = "def beta(y):\n    return y * 1\n"
TWO_FILE_REF_A = "def alpha(x):\n    return x + 1\n"
TWO_FILE_REF_B = "def beta(y):\n    return y * 2\n"


@pytest.fixture
def two_gold_files(tmp_path):
    """A real on-disk seed repo with TWO gold files, so the domain and extraction paths run end to end."""
    repo = tmp_path / "duo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text(TWO_FILE_SEED_A, encoding="utf-8")
    (repo / "pkg" / "b.py").write_text(TWO_FILE_SEED_B, encoding="utf-8")
    task = synthetic_task("duo", ["pkg/a.py", "pkg/b.py"],
                          {"pkg/a.py": TWO_FILE_REF_A, "pkg/b.py": TWO_FILE_REF_B})
    return tmp_path, task


def test_domain_excludes_a_real_non_py_json_gold_file(two_gold_files):
    """v1 creates no regions/changed_json key for a gold file that is neither .py nor .json, even when the file
    exists on disk and appears in the reference patch, so v2 must exclude it too."""
    repos_dir, _task = two_gold_files
    notes = repos_dir / "duo" / "pkg" / "notes.txt"
    notes.write_text("seed notes\n", encoding="utf-8")
    task = synthetic_task("duo", ["pkg/a.py", "pkg/notes.txt"],
                          {"pkg/a.py": TWO_FILE_REF_A, "pkg/notes.txt": "changed notes\n"})
    assert notes.is_file()
    assert v2.d1_region_files(task, repos_dir, defect_lines, normalize) == ["pkg/a.py"]
    r = row([diag(2, success=True, path="pkg/notes.txt"), read(3, path="pkg/notes.txt")],
            [view(3, path="pkg/notes.txt")], diagnoses=[record(path="pkg/notes.txt")], rejections=[])
    scope = v2.d1_region_files(task, repos_dir, defect_lines, normalize)
    v1_value = v1.extract_facts(r, task, StubReplayer(), defect_lines, repos_dir, normalize, None).evidence
    assert v2.d3_v2(r, scope, normalize) is v1_value


def test_domain_normalizes_gold_paths_like_v1(two_gold_files):
    """v1 normalizes gold paths before building its domain (furthest_bottleneck.py:811); dropping that in v2 would
    put an unnormalized key in the scope and silently change the per-file result."""
    repos_dir, _task = two_gold_files
    task = synthetic_task("duo", ["./pkg/a.py"], {"./pkg/a.py": TWO_FILE_REF_A})
    scope = v2.d1_region_files(task, repos_dir, defect_lines, normalize)
    assert scope == ["pkg/a.py"]
    r = row([read(1, path="pkg/a.py"), diag(2, success=True, path="pkg/a.py")],
            [view(1, path="pkg/a.py")], diagnoses=[record(path="pkg/a.py")], rejections=[])
    v1_value = v1.extract_facts(r, task, StubReplayer(), defect_lines, repos_dir, normalize, None).evidence
    assert v2.d3_v2(r, scope, normalize) is v1_value is T


def test_two_gold_file_domain_and_aggregation_end_to_end(two_gold_files):
    repos_dir, task = two_gold_files
    a, b = "pkg/a.py", "pkg/b.py"
    assert v2.d1_region_files(task, repos_dir, defect_lines, normalize) == [a, b]

    def build(calls, views, diagnoses):
        return row(calls, views, diagnoses=diagnoses, rejections=[])

    # a: complete read before an admitted diagnosis -> TRUE; b: admitted diagnosis before its read -> FALSE
    r = build([read(1, path=a), diag(2, success=True, path=a), diag(3, success=True, path=b), read(4, path=b)],
              [view(1, path=a), view(4, path=b)], [record(path=a), record(path=b)])
    scope = v2.d1_region_files(task, repos_dir, defect_lines, normalize)
    assert v2.call_position_violations(r, scope, normalize) == []
    assert v2.d3_file(r, a, normalize) is T and v2.d3_file(r, b, normalize) is F
    assert v2.d3_v2(r, scope, normalize) is F                     # tri_and over the two files
    facts, _desc = v2.extract_facts_v2(r, task, StubReplayer(), defect_lines, repos_dir, normalize, None)
    v1_value = v1.extract_facts(r, task, StubReplayer(), defect_lines, repos_dir, normalize, None).evidence
    assert facts.evidence is F and v1_value is F

    # row-global ordering across the two files: a decrease between files is a violation
    crossed = build([read(1, path=a), diag(4, success=True, path=a), diag(2, success=True, path=b)],
                    [view(1, path=a), view(1, path=b)], [record(path=a), record(path=b)])
    assert v2.call_position_violations(crossed, scope, normalize)
    with pytest.raises(v2.RowContractViolation):
        v2.extract_facts_v2(crossed, task, StubReplayer(), defect_lines, repos_dir, normalize, None)

    # both files TRUE -> row TRUE, and v1 agrees
    both = build([read(1, path=a), read(1, path=b), diag(2, success=True, path=a), diag(3, success=True, path=b)],
                 [view(1, path=a), view(1, path=b)], [record(path=a), record(path=b)])
    assert v2.d3_v2(both, scope, normalize) is T
    assert v1.extract_facts(both, task, StubReplayer(), defect_lines, repos_dir, normalize, None).evidence is T


# ============================================================================= scope and wiring
def test_scope_matches_the_task_gold_file_with_a_defect_region():
    scope = v2.d1_region_files(DIV, REPOS_DIR, defect_lines, normalize)
    assert scope == [normalize(g) for g in DIV.gold_files]


def test_extract_facts_v2_replaces_only_evidence():
    r = row([diag(1), read(2), diag(3)], [view(2)],
            diagnoses=[record(refused="evidence_requires_read"), record()], rejections=[rejection()], condition="qwen_selectorkind")
    base = v1.extract_facts(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    facts, descriptive = v2.extract_facts_v2(r, DIV, StubReplayer(), defect_lines, REPOS_DIR, normalize, None)
    assert base.evidence is F and facts.evidence is T
    assert dataclasses.replace(base, evidence=T) == facts
    assert set(descriptive) == {"D3_ATTEMPT_OBSERVED", "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT"}
