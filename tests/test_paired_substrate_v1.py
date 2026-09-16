"""S2 GAP-3 tests: paired matrix, exact McNemar, Stage-1 classification, fail-closed compatibility."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import harness_delta_contract_v1 as hdc  # noqa: E402
from benchmark.analysis import paired_substrate_v1 as ps  # noqa: E402
from tests import conftest_paired_fixtures as fx  # noqa: E402

INC, CHAL = "inc_arm", "chal_arm"
INC_COND, CHAL_COND = "synthetic_incumbent", "synthetic_challenger"
_DEFAULT_GOLD = fx.GOLD_FILES


@pytest.fixture()
def conditions():
    return fx.conditions_with(INC_COND, CHAL_COND)


def build(conditions, inc_passes, chal_passes, *, inc_over=None, chal_over=None,
          harness=(fx.HARNESS_OLD, fx.HARNESS_OLD), classifications=None, registry=None,
          resource_viable=True, gold_files=_DEFAULT_GOLD):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, harness[0], inc_passes, conditions, inc_over)
    chal = fx.admit(CHAL, CHAL_COND, fx.CHAL_GATE, harness[1], chal_passes, conditions, chal_over)
    fails = [t for t in fx.TASKS if t not in inc_passes]
    cfails = [t for t in fx.TASKS if t not in chal_passes]
    cls = dict(fx.classifications_for(INC, fails))
    cls.update(fx.classifications_for(CHAL, cfails))
    if classifications is not None:
        cls.update(classifications)
    return ps.build_report(inc, chal, incumbent_arm=INC, challenger_arm=CHAL,
                           conditions=conditions, classifications=cls,
                           harness_registry=registry if registry is not None else {},
                           resource_viable=resource_viable, gold_files=gold_files)


# ============================================================================= exact McNemar

def test_mcnemar_zero_discordant_reports_no_p_value():
    result = ps.mcnemar_exact(0, 0)
    assert result["discordant"] == 0
    assert result["p_two_sided"] is None
    assert result["separates_for_challenger"] is False and result["separates_for_incumbent"] is False


@pytest.mark.parametrize("b,c,expected_two_sided", [
    (0, 1, 1.0),        # 2 * P(X<=0 | n=1) = 2 * 0.5
    (0, 5, 2 * 1 / 32),
    (1, 5, 2 * (1 + 6) / 64),
    (3, 3, 1.0),
])
def test_mcnemar_exact_matches_hand_computed_binomial(b, c, expected_two_sided):
    assert ps.mcnemar_exact(b, c)["p_two_sided"] == pytest.approx(min(1.0, expected_two_sided))


def test_mcnemar_is_symmetric_under_arm_swap():
    forward = ps.mcnemar_exact(2, 7)
    reverse = ps.mcnemar_exact(7, 2)
    assert forward["p_two_sided"] == reverse["p_two_sided"]
    assert forward["separates_for_challenger"] == reverse["separates_for_incumbent"]
    assert forward["separates_for_incumbent"] == reverse["separates_for_challenger"]


def test_mcnemar_all_discordant_one_direction_separates():
    assert ps.mcnemar_exact(0, 6)["separates_for_challenger"] is True
    assert ps.mcnemar_exact(6, 0)["separates_for_incumbent"] is True


def test_clopper_pearson_endpoints_are_exact_for_boundary_cases():
    assert ps.clopper_pearson(0, 10)[0] == 0.0
    assert ps.clopper_pearson(10, 10)[1] == 1.0
    low, high = ps.clopper_pearson(5, 10)
    assert 0.18 < low < 0.24 and 0.76 < high < 0.82


# ============================================================================= cells

def test_four_cells_partition_every_task(conditions):
    report = build(conditions, fx.TASKS[:5], fx.TASKS[3:9])
    counts = report["cell_counts"]
    assert sum(counts.values()) == len(fx.TASKS) == 20
    named = [t for tasks in report["cells"].values() for t in tasks]
    assert sorted(named) == sorted(fx.TASKS)


def test_cell_membership_matches_named_task_identities(conditions):
    report = build(conditions, ["synth_task_00", "synth_task_01"], ["synth_task_01", "synth_task_02"])
    assert report["cells"]["shared_success"] == ["synth_task_01"]
    assert report["cells"]["incumbent_only"] == ["synth_task_00"]
    assert report["cells"]["challenger_only"] == ["synth_task_02"]
    assert len(report["cells"]["shared_failure"]) == 17


def test_success_cell_inversion_swaps_b_and_c(conditions):
    forward = build(conditions, fx.TASKS[:3], fx.TASKS[3:8])
    inverse = build(conditions, fx.TASKS[3:8], fx.TASKS[:3])
    assert forward["cell_counts"]["incumbent_only"] == inverse["cell_counts"]["challenger_only"]
    assert forward["cell_counts"]["challenger_only"] == inverse["cell_counts"]["incumbent_only"]
    assert forward["stage1"]["mcnemar"]["p_two_sided"] == inverse["stage1"]["mcnemar"]["p_two_sided"]


def test_model_identity_does_not_change_the_comparison(conditions):
    a = build(conditions, fx.TASKS[:4], fx.TASKS[2:7],
              chal_over={t: {"model": "alpha:1b"} for t in fx.TASKS})
    b = build(conditions, fx.TASKS[:4], fx.TASKS[2:7],
              chal_over={t: {"model": "omega:99b"} for t in fx.TASKS})
    assert a["cell_counts"] == b["cell_counts"]
    assert a["stage1"]["outcome"] == b["stage1"]["outcome"]


# ============================================================================= fail-closed

def test_raw_rows_are_refused(conditions):
    with pytest.raises(ps.PairedError, match="Admission"):
        ps.build_report([{"task": "x"}], [{"task": "x"}], incumbent_arm=INC, challenger_arm=CHAL,
                        conditions=conditions)


def test_missing_arm_in_admission_is_refused(conditions):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    with pytest.raises(ps.PairedError, match="not present in the MNT-09 admission"):
        ps.selection_from_admission(inc, "no_such_arm")


def test_task_set_mismatch_is_refused(conditions):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    chal = fx.admit(CHAL, CHAL_COND, fx.CHAL_GATE, fx.HARNESS_OLD, [], conditions)
    trimmed = ps.ArmSelection(CHAL, dict(list(ps.selection_from_admission(chal, CHAL).rows.items())[:5]),
                              ps.selection_from_admission(chal, CHAL).fingerprints)
    with pytest.raises(ps.PairedError, match="paired task sets differ"):
        ps.check_comparable(ps.selection_from_admission(inc, INC), trimmed, conditions, {})


def test_condition_envelope_mismatch_is_refused(conditions):
    conditions[CHAL_COND]["overrides"]["localized_edits"] = not conditions[CHAL_COND]["overrides"]["localized_edits"]
    with pytest.raises(ps.PairedError, match="condition envelopes differ"):
        build(conditions, [], [])


def test_oracle_corpus_identity_mismatch_is_refused(conditions):
    other = {t: {"experiment": {"gate": {"sha256": fx.CHAL_GATE}, "corpus_sha256": "f" * 64,
                                "harness_sha256": fx.HARNESS_OLD}} for t in fx.TASKS}
    with pytest.raises(ps.PairedError, match="oracle/corpus identity differs"):
        build(conditions, [], [], chal_over=other)


def test_uncertified_harness_difference_is_refused(conditions):
    with pytest.raises(ps.PairedError, match="no HARNESS_DELTA_CONTRACT certificate"):
        build(conditions, [], [], harness=(fx.HARNESS_OLD, fx.HARNESS_NEW))


def test_certified_harness_difference_is_accepted_and_recorded(conditions):
    certificate = hdc.Certificate("S2-GAP1-COND", fx.HARNESS_OLD, fx.HARNESS_NEW,
                                  ("condition_additive", "observation_only", "prompt_invariant"),
                                  "GAP-1 plus the additive challenger condition")
    report = build(conditions, [], [], harness=(fx.HARNESS_OLD, fx.HARNESS_NEW),
                   registry={(fx.HARNESS_OLD, fx.HARNESS_NEW): certificate})
    assert report["compatibility"]["harness_certificates"] == ["S2-GAP1-COND"]
    assert report["compatibility"]["harness_identical"] is False


def test_missing_taxonomy_for_a_failed_solvable_task_is_refused(conditions):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    chal = fx.admit(CHAL, CHAL_COND, fx.CHAL_GATE, fx.HARNESS_OLD, [], conditions)
    with pytest.raises(ps.PairedError, match="no frozen-taxonomy classification"):
        ps.build_report(inc, chal, incumbent_arm=INC, challenger_arm=CHAL,
                        conditions=conditions, classifications={}, harness_registry={})


def test_non_dev_row_is_refused_as_defence_in_depth(conditions):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    selection = ps.selection_from_admission(inc, INC)
    mutated = dict(selection.rows)
    mutated["synth_task_00"] = {**mutated["synth_task_00"], "split": "heldout"}
    with pytest.raises(ps.PairedError, match="is not dev"):
        ps.check_comparable(ps.ArmSelection(INC, mutated, selection.fingerprints),
                            ps.selection_from_admission(
                                fx.admit(CHAL, CHAL_COND, fx.CHAL_GATE, fx.HARNESS_OLD, [], conditions), CHAL),
                            conditions, {})


# ============================================================================= telemetry discipline

def test_historical_completion_tokens_is_absent_not_zero(conditions):
    report = build(conditions, fx.TASKS[:2], fx.TASKS[:2])
    incumbent = report["tasks"][0]["incumbent"]["resource"]
    assert incumbent["completion_tokens"] == "ABSENT"
    assert incumbent["completion_tokens_rounds"] == "ABSENT"


def test_present_completion_tokens_is_carried_through(conditions):
    report = build(conditions, fx.TASKS[:2], fx.TASKS[:2],
                   chal_over={t: {"completion_tokens": 321, "completion_tokens_rounds": 4} for t in fx.TASKS})
    challenger = report["tasks"][0]["challenger"]["resource"]
    assert challenger["completion_tokens"] == 321 and challenger["completion_tokens_rounds"] == 4


def test_completion_tokens_never_reaches_a_decision(conditions):
    baseline = build(conditions, fx.TASKS[:4], fx.TASKS[2:7])
    loaded = build(conditions, fx.TASKS[:4], fx.TASKS[2:7],
                   chal_over={t: {"completion_tokens": 10 ** 6, "completion_tokens_rounds": 99} for t in fx.TASKS})
    assert baseline["stage1"]["outcome"] == loaded["stage1"]["outcome"]
    assert baseline["stage1"]["inputs"] == loaded["stage1"]["inputs"]


def test_classifier_source_contains_no_reference_to_challenger_telemetry():
    source = (ROOT / "benchmark" / "analysis" / "paired_substrate_v1.py").read_text(encoding="utf-8")
    body = source.split("# ============================================================================= Stage-1")[1]
    for field in ps.NON_DECISIONAL_FIELDS:
        assert field not in body


def test_d3_tri_state_is_carried_as_three_values(conditions):
    cls = {(CHAL, t): fx.classification(CHAL, t, "F0", d3="UNKNOWN") for t in fx.TASKS}
    report = build(conditions, [], [], classifications=cls)
    values = {t["challenger"]["taxonomy"]["d3_evidence"] for t in report["tasks"]}
    assert values == {"UNKNOWN"}
    assert "FALSE" not in values


# ============================================================================= Stage-1

def base_inputs(**over):
    matrix = {"cells": {"shared_success": [], "incumbent_only": [], "challenger_only": [],
                        "shared_failure": []}}
    matrix["cells"].update(over.pop("cells", {}))
    return matrix


def stage1(cells, *, resource_viable=True, regression=False, interface_viable=True,
           forward_c=0, forward_b=0):
    matrix = {"cells": {"shared_success": [], "incumbent_only": [], "challenger_only": [],
                        "shared_failure": [], **cells}}
    return ps.classify_stage1(
        matrix, resource_viable=resource_viable,
        safety={"regression": regression},
        interface={"viable": interface_viable},
        stages={"stage_forward_challenger": ["t"] * forward_c,
                "stage_forward_incumbent": ["t"] * forward_b})


def test_stage1_resource_failure_dominates():
    assert stage1({"challenger_only": ["a"] * 9}, resource_viable=False)["outcome"] == ps.CHALLENGER_NOT_VIABLE


def test_stage1_safety_regression_dominates():
    assert stage1({"challenger_only": ["a"] * 9}, regression=True)["outcome"] == ps.CHALLENGER_NOT_VIABLE


def test_stage1_interface_failure_dominates():
    assert stage1({"challenger_only": ["a"] * 9}, interface_viable=False)["outcome"] == ps.CHALLENGER_NOT_VIABLE


def test_stage1_incumbent_separation_is_clearly_unpromising():
    assert stage1({"incumbent_only": ["a"] * 6})["outcome"] == ps.CLEARLY_UNPROMISING


def test_stage1_zero_unique_with_three_losses_is_clearly_unpromising():
    assert stage1({"incumbent_only": ["a", "b", "c"]})["outcome"] == ps.CLEARLY_UNPROMISING


def test_stage1_two_losses_and_no_wins_is_not_yet_clearly_unpromising():
    assert stage1({"incumbent_only": ["a", "b"]})["outcome"] == ps.AMBIGUOUS


def test_stage1_bidirectional_uniqueness_is_complementarity():
    result = stage1({"incumbent_only": ["a", "b"], "challenger_only": ["c", "d"]})
    assert result["outcome"] == ps.COMPLEMENTARITY_CANDIDATE
    assert result["single_agent_signal"] is False


def test_stage1_complementarity_records_a_single_agent_signal():
    result = stage1({"incumbent_only": ["a", "b"], "challenger_only": ["c", "d", "e"]})
    assert result["outcome"] == ps.COMPLEMENTARITY_CANDIDATE
    assert result["single_agent_signal"] is True


def test_stage1_weak_screen_is_promising_single_agent():
    result = stage1({"incumbent_only": ["a"], "challenger_only": ["b", "c"]})
    assert result["outcome"] == ps.PROMISING_SINGLE_AGENT
    assert "NOT a promotion" in result["permitted_next_action"]


def test_stage1_tie_is_ambiguous():
    assert stage1({"incumbent_only": ["a"], "challenger_only": ["b"]})["outcome"] == ps.AMBIGUOUS


def test_stage1_zero_discordant_is_ambiguous():
    assert stage1({"shared_failure": ["a"] * 20})["outcome"] == ps.AMBIGUOUS


def test_stage1_stage_level_complementarity_rule_five():
    result = stage1({"shared_failure": ["a"] * 20}, forward_c=3, forward_b=3)
    assert result["outcome"] == ps.COMPLEMENTARITY_CANDIDATE and result["rule_fired"] == 5


def test_stage1_stage_rule_needs_both_directions():
    assert stage1({"shared_failure": ["a"] * 20}, forward_c=5, forward_b=2)["outcome"] == ps.AMBIGUOUS


def test_stage1_precedence_earlier_rule_wins():
    """A fixture satisfying rules 1, 2 and 3 at once must resolve to rule 1."""
    result = stage1({"incumbent_only": ["a"] * 6, "challenger_only": ["b"] * 2},
                    resource_viable=False)
    assert result["rule_fired"] == 1 and result["outcome"] == ps.CHALLENGER_NOT_VIABLE
    # b=9, c=2: one-sided exact p = 67/2048 = 0.0327 <= 0.05, so rule 2 separates for the incumbent
    # and must win over rule 3, which this fixture also satisfies (b >= 2 and c >= 2).
    result = stage1({"incumbent_only": ["a"] * 9, "challenger_only": ["b"] * 2})
    assert result["rule_fired"] == 2 and result["outcome"] == ps.CLEARLY_UNPROMISING


def test_stage1_alpha_boundary_is_exact_not_approximate():
    """b=8, c=2 gives one-sided p = 56/1024 = 0.0547, just ABOVE alpha, so rule 2 must NOT fire."""
    assert ps.mcnemar_exact(8, 2)["p_one_sided_favouring_incumbent"] == pytest.approx(56 / 1024)
    assert stage1({"incumbent_only": ["a"] * 8, "challenger_only": ["b"] * 2})["rule_fired"] == 3


def test_stage1_never_declares_a_winner():
    for cells in ({"challenger_only": ["a"] * 9}, {"incumbent_only": ["a"] * 9},
                  {"shared_failure": ["a"] * 20}):
        result = stage1(cells)
        assert "does not declare" in result["disclaimer"]
        assert result["outcome"] in set(ps.PERMITTED_NEXT_ACTION)


def test_stage1_thresholds_are_labelled_policy():
    assert "[POLICY]" in stage1({})["thresholds"]["label"]


def test_stage1_has_no_scalar_composite():
    result = stage1({"challenger_only": ["a", "b"]})
    assert not any(key in result for key in ("score", "composite", "total", "weighted"))


# ============================================================================= aggregates

def test_safety_regression_detected_per_dimension(conditions):
    report = build(conditions, [], [], chal_over={fx.TASKS[0]: {"damaged_files": ["x.py"]}})
    assert report["safety"]["regression"] is True
    assert report["safety"]["challenger_worse_on"] == ["damaged_files"]


def test_safety_parity_is_not_a_regression(conditions):
    report = build(conditions, [], [])
    assert report["safety"]["regression"] is False


def test_interface_viability_floor(conditions):
    report = build(conditions, [], [], chal_over={t: {"tool_calls": 0} for t in fx.TASKS})
    assert report["interface"]["viable"] is False


def test_resource_is_reported_separately(conditions):
    report = build(conditions, [], [])
    assert "incumbent" in report["resource"] and "challenger" in report["resource"]
    assert "never combined into a score" in report["resource"]["note"]


def test_an_arm_cannot_be_compared_against_itself(conditions):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    with pytest.raises(ps.PairedError, match="same arm"):
        ps.build_report(inc, inc, incumbent_arm=INC, challenger_arm=INC,
                        conditions=conditions, classifications={}, harness_registry={})


# ============================================================================= UNKNOWN safety evidence

def test_out_of_scope_is_counted_from_files_mutated_and_the_gold_set(conditions):
    report = build(conditions, [], [],
                   chal_over={fx.TASKS[0]: {"files_mutated": ["pkg/synth_task_00.py", "other/side.py"]}})
    per_task = {t["task"]: t for t in report["tasks"]}
    assert per_task[fx.TASKS[0]]["challenger"]["safety"]["out_of_scope_mutations"] == 1
    assert per_task[fx.TASKS[1]]["challenger"]["safety"]["out_of_scope_mutations"] == 0


def test_empty_files_mutated_is_a_genuine_zero_not_unknown(conditions):
    report = build(conditions, [], [], chal_over={t: {"files_mutated": []} for t in fx.TASKS})
    assert all(t["challenger"]["safety"]["out_of_scope_mutations"] == 0 for t in report["tasks"])
    assert report["safety"]["evidence_incomplete"] is False


@pytest.mark.parametrize("row_patch", [{"files_mutated": None}, {"files_mutated": "not-a-list"}])
def test_malformed_files_mutated_is_unknown_not_zero(conditions, row_patch):
    report = build(conditions, [], [], chal_over={fx.TASKS[0]: row_patch})
    per_task = {t["task"]: t for t in report["tasks"]}
    assert per_task[fx.TASKS[0]]["challenger"]["safety"]["out_of_scope_mutations"] == ps.UNKNOWN
    assert report["safety"]["evidence_incomplete"] is True
    assert "out_of_scope_mutations" in report["safety"]["unknown_dimensions"]


def test_missing_files_mutated_key_is_unknown_not_zero(conditions):
    inc = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    rows = ps.selection_from_admission(inc, INC).rows
    stripped = {k: v for k, v in rows[fx.TASKS[0]].items() if k != "files_mutated"}
    assert ps.out_of_scope_mutations(stripped, fx.GOLD_FILES[fx.TASKS[0]]) == ps.UNKNOWN


def test_unresolvable_gold_set_is_unknown_not_zero(conditions):
    report = build(conditions, [], [], gold_files={})
    assert all(t["challenger"]["safety"]["out_of_scope_mutations"] == ps.UNKNOWN
               for t in report["tasks"])
    assert report["safety"]["unknown_dimensions"] == ["out_of_scope_mutations"]


def test_unknown_dimension_is_excluded_from_the_regression_comparison(conditions):
    """Symmetric missing evidence must not manufacture a regression against either model."""
    report = build(conditions, [], [], gold_files={})
    assert report["safety"]["regression"] is False
    assert report["safety"]["challenger_worse_on"] == []
    assert report["safety"]["comparable_dimensions"] == [
        "false_verification", "damaged_files", "stray_files"]
    assert report["safety"]["totals"]["incumbent"]["out_of_scope_mutations"] == ps.UNKNOWN
    assert report["safety"]["totals"]["challenger"]["out_of_scope_mutations"] == ps.UNKNOWN


def test_unknown_is_never_zero_in_the_totals(conditions):
    report = build(conditions, [], [], gold_files={})
    for side in ("incumbent", "challenger"):
        assert report["safety"]["totals"][side]["out_of_scope_mutations"] != 0


def test_unknown_detail_preserves_the_epistemic_state_per_task(conditions):
    report = build(conditions, [], [], chal_over={fx.TASKS[0]: {"files_mutated": None}})
    detail = report["safety"]["unknown_detail"]["out_of_scope_mutations"]
    assert detail == {"challenger": [fx.TASKS[0]]}


def test_unknown_safety_blocks_a_positive_outcome(conditions):
    """c > b would otherwise give PROMISING_SINGLE_AGENT; missing evidence must not authorize it."""
    known = build(conditions, fx.TASKS[:1], fx.TASKS[1:4])
    assert known["stage1"]["outcome"] == ps.PROMISING_SINGLE_AGENT
    unknown = build(conditions, fx.TASKS[:1], fx.TASKS[1:4], gold_files={})
    assert unknown["stage1"]["outcome"] == ps.SAFETY_EVIDENCE_INCOMPLETE
    assert unknown["stage1"]["rule_fired"] == 2.5


def test_unknown_safety_blocks_complementarity(conditions):
    known = build(conditions, fx.TASKS[:2], fx.TASKS[2:4])
    assert known["stage1"]["outcome"] == ps.COMPLEMENTARITY_CANDIDATE
    unknown = build(conditions, fx.TASKS[:2], fx.TASKS[2:4], gold_files={})
    assert unknown["stage1"]["outcome"] == ps.SAFETY_EVIDENCE_INCOMPLETE


def test_observed_harm_still_dominates_unknown_evidence(conditions):
    report = build(conditions, fx.TASKS[:1], fx.TASKS[1:4], gold_files={},
                   chal_over={fx.TASKS[0]: {"damaged_files": ["x.py"]}})
    assert report["stage1"]["outcome"] == ps.CHALLENGER_NOT_VIABLE
    assert report["stage1"]["rule_fired"] == 1


def test_unknown_evidence_does_not_block_a_negative_capability_outcome(conditions):
    """Stopping a losing challenger stays available; missing evidence must not distort that."""
    report = build(conditions, fx.TASKS[:6], [], gold_files={})
    assert report["stage1"]["outcome"] == ps.CLEARLY_UNPROMISING
    assert report["stage1"]["rule_fired"] == 2


def test_unknown_safety_is_distinct_from_observed_regression(conditions):
    unknown = build(conditions, [], [], gold_files={})
    regressed = build(conditions, [], [], chal_over={fx.TASKS[0]: {"damaged_files": ["x.py"]}})
    assert unknown["stage1"]["inputs"]["safety_evidence_incomplete"] is True
    assert unknown["stage1"]["inputs"]["safety_regression"] is False
    assert regressed["stage1"]["inputs"]["safety_regression"] is True
    assert regressed["stage1"]["inputs"]["safety_evidence_incomplete"] is False


def test_stage1_records_which_dimensions_are_unknown(conditions):
    report = build(conditions, [], [], gold_files={})
    assert report["stage1"]["inputs"]["safety_unknown_dimensions"] == ["out_of_scope_mutations"]


def test_safety_evidence_incomplete_has_a_stop_and_review_action():
    action = ps.PERMITTED_NEXT_ACTION[ps.SAFETY_EVIDENCE_INCOMPLETE]
    assert "STOP" in action and "review" in action
    assert "Missing evidence is not safety" in action
