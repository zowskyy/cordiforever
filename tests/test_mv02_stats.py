"""MV-02 v2.1 exact sign-test machinery (spec §4, §5, §9)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import FAIL, PASS, UNRESOLVED  # noqa: E402
from scripts.monitor_validity_v2 import stats  # noqa: E402


def test_ranks_and_coverage_match_the_specification():
    assert stats.sign_test_rank(8) == 1
    assert stats.sign_test_rank(9) == 2
    assert stats.sign_test_rank(10) == 2
    assert stats.sign_test_rank(20) == 6
    assert stats.coverage(10) == 0.978515625
    assert round(stats.coverage(20), 6) == 0.958611
    assert stats.sign_test_rank(0) is None


def test_interval_uses_order_statistics_k_and_n_plus_1_minus_k():
    diffs = list(range(1, 21))
    assert stats.interval(diffs) == (6, 15)
    assert stats.interval(list(range(1, 11))) == (2, 9)


def test_strict_inclusion_pass_fail_unresolved():
    inside = [0.001 * i for i in range(20)]
    assert stats.equivalence_decision(inside, 0.02, n_required=20)["decision"] == PASS
    outside = [0.05 + 0.001 * i for i in range(20)]
    assert stats.equivalence_decision(outside, 0.02, n_required=20)["decision"] == FAIL
    straddle = [-0.06 + 0.006 * i for i in range(20)]
    assert stats.equivalence_decision(straddle, 0.02, n_required=20)["decision"] == UNRESOLVED


def test_touching_a_margin_is_never_pass():
    at_margin = [0.0] * 6 + [0.02] * 14
    result = stats.equivalence_decision(at_margin, 0.02, n_required=20)
    assert result["interval"][1] == 0.02
    assert result["decision"] == UNRESOLVED
    at_low_margin = [0.02] * 20
    assert stats.equivalence_decision(at_low_margin, 0.02, n_required=20)["decision"] == FAIL


def test_fewer_than_required_observations_is_unresolved():
    result = stats.equivalence_decision([0.0] * 9, 16.0, n_required=10)
    assert result["decision"] == UNRESOLVED
    assert result["interval"] is None
