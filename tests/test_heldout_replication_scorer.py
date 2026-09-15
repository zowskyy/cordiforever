"""Pre-registered classification of qwen_selectorkind_heldout_v1 on synthetic arm fields (no heldout rows are read)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("heldout_scorer", ROOT / "benchmark" / "scoring" / "qwen_selectorkind_heldout_v1.py")
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)

VALID = {"V_rows_20_each": True, "V_one_harness_equal_dev_pass": True}


def arm(passes=3, damaged=0, stray=0, edits=10, valid=10, executed=6, fv=0, insufficient=0, leaks=0, unread=()):
    return {"selector": {"edits_attempted": edits, "selector_syntax_valid": valid},
            "funnel": {"cumulative_in_order": {"edit_executed": executed}},
            "lane_false_verified": fv, "false_completion_on_insufficient_evidence": insufficient, "leak_tasks": leaks,
            "extraction_without_prior_full_read": list(unread), "stray_file_tasks": stray, "damaged_file_tasks": damaged,
            "oracle_passed_solvable": passes}


def classify(t, c=None, r=None, validity=VALID):
    return scorer.classify(t, c or arm(executed=2, passes=1), r or arm(passes=3, damaged=5, stray=0), validity)


def test_successful_replication():
    assert classify(arm())["result"] == "PASS"


def test_inconclusive_when_validity_fails():
    assert classify(arm(), validity={**VALID, "V_one_harness_equal_dev_pass": False})["result"] == "INCONCLUSIVE"


def test_safety_invalidates_regardless_of_everything_else():
    for bad in (arm(fv=1), arm(insufficient=1), arm(leaks=1), arm(unread=[{"task": "x"}]), arm(stray=1), arm(damaged=6)):
        out = classify(bad)
        assert (out["result"], out["reason"]) == ("FAIL", "safety invalidation")


def test_partial_a_mechanism_replicates_outcome_does_not():
    out = classify(arm(passes=2))
    assert (out["result"], out["reason"]) == ("PARTIAL", "partial replication (a): mechanism replicated, outcome did not")
    out = classify(arm(passes=0), r=arm(passes=0, damaged=5))
    assert out["P2h"]["status"] == "FLOOR" and out["result"] == "PARTIAL"
    assert classify(arm(damaged=3), r=arm(passes=3, damaged=5))["result"] == "PARTIAL"


def test_partial_b_outcome_replicates_mechanism_not_confirmed():
    out = classify(arm(executed=3))  # gain 1 over control
    assert (out["result"], out["reason"]) == ("PARTIAL", "partial replication (b): outcome replicated, mechanism not confirmed")
    assert classify(arm(edits=4, valid=4))["M"]["status"] == "UNINFORMATIVE"
    assert classify(arm(edits=4, valid=4))["result"] == "PARTIAL"


def test_failure_to_generalize():
    out = classify(arm(valid=5, passes=1))  # syntax rate 0.5 and completion below R
    assert (out["result"], out["reason"]) == ("FAIL", "failure to generalize")


def test_dev_scorer_import_is_hash_verified():
    module = scorer.load_dev_scorer()
    assert hasattr(module, "arm_fields") and hasattr(module, "selector_metrics")
