"""RC-5 prevention: every combined state is reachable through the REAL run_all -> combine path (injected runners)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import FAIL, INVALID, NOT_RUN, QUALIFIED, UNRESOLVED, VALID  # noqa: E402
from scripts.monitor_validity_v2 import combine, mv02c_enforcement as mc, run_all  # noqa: E402
from tests.mv02_fixtures import MIB, FakeRunner, SyntheticB  # noqa: E402


def c_runner(*, silent_pass_case=None, mismatch_case=None, invalid_case=None):
    def run(case, scratch):
        classification = mc.SILENT_SAMPLER_DEATH_GATE_PASS if case.case_id == silent_pass_case else \
            case.expected["classification"] if case.expected["kind"] == "exact" else mc.SILENT_SAMPLER_DEATH_GATE_FAIL
        record = {"case_id": case.case_id, "classification": classification,
                  "match": case.case_id not in (silent_pass_case, mismatch_case),
                  "run_status": INVALID if case.case_id == invalid_case else VALID,
                  "invalid_reasons": ["frozen call-order self-check failed"] if case.case_id == invalid_case else []}
        return record, {"case_id": case.case_id}
    return run


def child_factory(scratch):
    return Path(scratch) / "child_b_reference.py"


def attempt(tmp_path, *, c=None, b=None, a=None):
    b_runner = b or SyntheticB()
    a_runner = a or FakeRunner()
    result = run_all.run_all(tmp_path / "attempt", c_case_runner=c or c_runner(), b_monitor_runner=b_runner,
                             b_child_factory=child_factory, a_runner=a_runner)
    return result, b_runner, a_runner


def test_qualified_is_reachable(tmp_path):
    result, _, _ = attempt(tmp_path)
    assert result["combined"] == {"run_status": VALID, "verdict": QUALIFIED, "components": {
        "C": {"run_status": VALID, "verdict": "PASS"}, "B": {"run_status": VALID, "verdict": "PASS"},
        "A": {"run_status": VALID, "verdict": "PASS"}}}


@pytest.mark.parametrize("name,kwargs", [
    ("a_slowdown", {"a": FakeRunner(m_factor=1.10)}),
    ("a_speedup", {"a": FakeRunner(m_factor=0.90)}),
    ("b1_offset", {"b": SyntheticB(offset=40 * MIB)}),
    ("b2_step_miss", {"b": SyntheticB(capture=0.0)}),
    ("b3_slow_pace", {"b": SyntheticB(gap=0.6)}),
    ("c_silent_gate_pass", {"c": c_runner(silent_pass_case="C9")}),
    ("c_case_mismatch", {"c": c_runner(mismatch_case="C2")}),
])
def test_fail_is_reachable_through_each_trigger(tmp_path, name, kwargs):
    result, _, _ = attempt(tmp_path, **kwargs)
    assert result["combined"]["run_status"] == VALID and result["combined"]["verdict"] == FAIL, name


@pytest.mark.parametrize("name,kwargs", [
    ("a_straddle", {"a": FakeRunner(spread=[-0.05 + 0.005 * i for i in range(20)])}),
    ("b_nine_adequate", {"b": SyntheticB(a0_by_invocation={4: 1000})}),
    ("b_precondition_invocation_1", {"b": SyntheticB(a0_mib=1000)}),
])
def test_unresolved_is_reachable(tmp_path, name, kwargs):
    result, _, _ = attempt(tmp_path, **kwargs)
    assert result["combined"]["run_status"] == VALID and result["combined"]["verdict"] == UNRESOLVED, name


@pytest.mark.parametrize("name,kwargs", [
    ("b_child_crash", {"b": SyntheticB(returncode=1)}),
    ("c_call_order", {"c": c_runner(invalid_case="C4")}),
    ("a_u_timeout", {"a": FakeRunner(fail={("U", 3): "timeout"})}),
])
def test_invalid_is_a_run_status_without_verdict(tmp_path, name, kwargs):
    result, _, _ = attempt(tmp_path, **kwargs)
    assert result["combined"]["run_status"] == INVALID and result["combined"]["verdict"] is None, name


@pytest.mark.parametrize("c", [c_runner(silent_pass_case="C9"), c_runner(invalid_case="C1")])
def test_c_fail_or_invalid_stops_before_any_b_allocation_or_a(tmp_path, c):
    result, b_runner, a_runner = attempt(tmp_path, c=c)
    assert b_runner.commands == [] and a_runner.calls == []
    assert result["B"] is None and result["A"] is None
    assert result["combined"]["components"]["B"] == NOT_RUN == result["combined"]["components"]["A"]


def test_b_precondition_still_runs_a(tmp_path):
    result, b_runner, a_runner = attempt(tmp_path, b=SyntheticB(a0_mib=1000))
    assert len(b_runner.commands) == 1 and len(a_runner.calls) == 43


def test_b_invalid_stops_a(tmp_path):
    result, _, a_runner = attempt(tmp_path, b=SyntheticB(wrong_parent=True))
    assert a_runner.calls == [] and result["A"] is None


def test_out_of_order_combination_is_never_qualified():
    c = {"run_status": VALID, "c_verdict": "PASS"}
    assert combine.combine(c, None, None)["run_status"] == INVALID


def test_cli_refuses_existing_attempt_directory(tmp_path):
    assert run_all.main(["--attempt-dir", str(tmp_path)]) == 2
