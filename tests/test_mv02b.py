"""MV-02B analysis and executor tests with synthetic sidecars and injected monitor runners (no real child)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import FAIL, INVALID, PASS, UNRESOLVED, VALID  # noqa: E402
from scripts.monitor_validity_v2 import child_b_reference as child_b  # noqa: E402
from scripts.monitor_validity_v2 import mv02b_measurement as mb  # noqa: E402
from tests.mv02_fixtures import SyntheticB  # noqa: E402

MIB = 1024 * 1024


def _child_factory(scratch):
    return Path(scratch) / "child_b_reference.py"


def _run(tmp_path, **kwargs):
    runner = SyntheticB(**kwargs)
    return mb.execute(tmp_path, monitor_runner=runner, child_factory=_child_factory), runner


def test_x_rule_boundaries_follow_the_frozen_formula():
    rule = dict(select=True, fixed_x_mib=None, x_target_mib=144, x_min_mib=80, required_free_mib=1152)
    assert child_b.choose_x(1296 * MIB, **rule) == 144
    assert child_b.choose_x(1296 * MIB - 1, **rule) == 80
    assert child_b.choose_x(1232 * MIB, **rule) == 80
    assert child_b.choose_x(1232 * MIB - 1, **rule) is None
    fixed = dict(select=False, x_target_mib=None, x_min_mib=None, required_free_mib=1152)
    assert child_b.choose_x(1232 * MIB, fixed_x_mib=80, **fixed) == 80
    assert child_b.choose_x(1232 * MIB - 1, fixed_x_mib=80, **fixed) is None
    assert child_b.choose_x(1296 * MIB - 1, fixed_x_mib=144, **fixed) is None


def test_perfect_attribution_passes(tmp_path):
    result, runner = _run(tmp_path)
    assert result["run_status"] == VALID and result["verdict"] == PASS
    assert result["b1"]["decision"] == PASS and result["b2"]["decision"] == PASS and result["b3"]["decision"] == PASS
    assert result["adequate_invocations"] == 10 and len(runner.commands) == 10


def test_x_is_fixed_after_invocation_1_and_never_resized(tmp_path):
    result, runner = _run(tmp_path, a0_by_invocation={1: 1296, 2: 5000})
    assert "--select-x" in runner.commands[0]
    for command in runner.commands[1:]:
        assert command[command.index("--fixed-x") + 1] == "144"
    assert all(p["x_mib"] == 144 for p in result["invocations"])


def test_later_precondition_failure_is_inadequate_and_not_replaced(tmp_path):
    result, runner = _run(tmp_path, a0_by_invocation={4: 1000})
    assert len(runner.commands) == 10
    assert result["invocations"][3]["status"] == "PRECONDITION_FAILED"
    assert result["adequate_invocations"] == 9
    assert result["b1"]["decision"] == UNRESOLVED and result["verdict"] == UNRESOLVED


def test_invocation_1_precondition_makes_b_unresolved_and_stops(tmp_path):
    result, runner = _run(tmp_path, a0_mib=1000)
    assert len(runner.commands) == 1
    assert result["verdict"] == UNRESOLVED and result["not_run_invocations"] == list(range(2, 11))


def test_attribution_offset_beyond_t_fails_b1(tmp_path):
    result, _ = _run(tmp_path, offset=40 * MIB)
    assert result["b1"]["decision"] == FAIL and result["verdict"] == FAIL


def test_step_miss_fails_b2(tmp_path):
    result, _ = _run(tmp_path, capture=0.0)
    assert result["b2"]["decision"] == FAIL and result["verdict"] == FAIL


def test_launcher_is_included_in_the_reference(tmp_path):
    result, _ = _run(tmp_path)
    assert all(abs(p["b1_error"]) < 1 for p in result["invocations"])


def test_b3_fails_on_slow_sampling_within_an_invocation(tmp_path):
    result, _ = _run(tmp_path, gap=0.6)
    assert result["b3"]["decision"] == FAIL


def test_b3_never_bridges_invocations():
    fast = {"invocation": 1, "status": "ADEQUATE", "sample_times": [i * 0.25 for i in range(40)]}
    later = {"invocation": 2, "status": "ADEQUATE", "sample_times": [10_000 + i * 0.25 for i in range(40)]}
    assert mb.b3_decision([fast, later])["decision"] == PASS


def test_b3_unresolved_when_a_required_invocation_has_fewer_than_8_samples():
    short = {"invocation": 1, "status": "INADEQUATE", "sample_times": [0.0, 0.25, 0.5]}
    fine = {"invocation": 2, "status": "ADEQUATE", "sample_times": [i * 0.25 for i in range(40)]}
    assert mb.b3_decision([short, fine])["decision"] == UNRESOLVED
    slow = {"invocation": 3, "status": "ADEQUATE", "sample_times": [i * 0.6 for i in range(40)]}
    assert mb.b3_decision([short, slow])["decision"] == FAIL


def test_guard_band_and_minimum_in_window_samples(tmp_path):
    result, _ = _run(tmp_path, gap=0.45)
    counts = result["invocations"][0]["in_window_counts"]
    assert all(count >= 4 for count in counts.values())
    sparse, _ = _run(tmp_path / "sparse", gap=0.7)
    assert sparse["invocations"][0]["status"] == "INADEQUATE"


def test_invalid_conditions_stop_b(tmp_path):
    for kwargs, fragment in [({"returncode": 1}, "returncode"), ({"wrong_parent": True}, "pid tree"),
                             ({"events": [{"event": "timeout"}]}, "timeout"), ({"drop_sidecar": True}, "sidecar"),
                             ({"drop_launcher_ws": True}, "reference working set")]:
        result, runner = _run(tmp_path / fragment.replace(" ", "_"), **kwargs)
        assert result["run_status"] == INVALID and result["verdict"] is None, kwargs
        assert len(runner.commands) == 1
        assert any(fragment in reason for reason in result["invalid_reasons"]), (kwargs, result["invalid_reasons"])


def test_invalid_mid_run_stops_without_replacement(tmp_path):
    result, runner = _run(tmp_path, bad_parent_on=5)
    assert result["run_status"] == INVALID and len(runner.commands) == 5


def test_every_page_of_the_allocation_is_touched():
    block = child_b.allocate_and_touch(1)
    assert len(block) == MIB
    assert all(block[offset] == 1 for offset in range(0, len(block), 4096))


def test_b2_tolerance_is_2t_not_t(tmp_path):
    # a monitor capturing 5/6 of a 144 MiB step has a 24 MiB step error: outside T, inside 2T
    result, _ = _run(tmp_path, capture=5 / 6)
    assert result["b2"]["decision"] == PASS
    assert result["b1"]["decision"] == FAIL
