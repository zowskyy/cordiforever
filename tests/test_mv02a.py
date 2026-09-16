"""MV-02A tests with injected runners (no real timing, no monitor)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import FAIL, INVALID, PASS, UNRESOLVED, VALID  # noqa: E402
from scripts.monitor_validity_v2 import mv02a_perturbation as ma  # noqa: E402
from tests.mv02_fixtures import FakeRunner  # noqa: E402


def test_pair_order_is_one_based_odd_m_first():
    assert ma.pair_order(1) == ("M", "U")
    assert ma.pair_order(2) == ("U", "M")
    assert ma.pair_order(19) == ("M", "U") and ma.pair_order(20) == ("U", "M")
    with pytest.raises(ValueError):
        ma.pair_order(0)


def test_frozen_policy_and_executor_signature():
    assert ma.FROZEN_A == {"pairs": 20, "alpha": 0.05, "tolerance_relative": 0.02, "target_duration_s": 8.0,
                           "warmups": 3, "warmup_iterations": 10_000_000, "timeout_s": 120}
    assert list(inspect.signature(ma.execute).parameters) == ["scratch", "runner"]


def test_execution_sequence_timeouts_and_iterations(tmp_path):
    runner = FakeRunner()
    result = ma.execute(tmp_path, runner=runner)
    kinds = [kind for kind, _, _ in runner.calls]
    assert kinds[:3] == ["U", "U", "U"]
    assert kinds[3:] == ["M", "U", "U", "M"] * 10
    assert all(timeout == 120 for _, _, timeout in runner.calls)
    assert runner.calls[0][1][runner.calls[0][1].index("--iterations") + 1] == "10000000"
    assert runner.calls[3][1][runner.calls[3][1].index("--iterations") + 1] == "40000000"
    assert all("--result-file" in command for _, command, _ in runner.calls)
    assert result["iterations"] == 40_000_000 and [p["pair_number"] for p in result["pairs"]] == list(range(1, 21))


def test_equal_durations_pass(tmp_path):
    result = ma.execute(tmp_path, runner=FakeRunner())
    assert result["run_status"] == VALID and result["verdict"] == PASS
    assert result["relative"]["rank_k"] == 6 and result["relative"]["n"] == 20


def test_monitored_slowdown_fails(tmp_path):
    result = ma.execute(tmp_path, runner=FakeRunner(m_factor=1.10))
    assert result["verdict"] == FAIL


def test_straddling_differences_are_unresolved(tmp_path):
    spread = [-0.05 + 0.005 * i for i in range(20)]
    result = ma.execute(tmp_path, runner=FakeRunner(spread=spread))
    assert result["verdict"] == UNRESOLVED


def test_relative_gates_absolute_is_descriptive(tmp_path):
    result = ma.execute(tmp_path, runner=FakeRunner(m_factor=1.01, u_seconds=100.0))
    assert result["verdict"] == PASS
    assert result["descriptive"]["absolute_median_s"] == pytest.approx(1.0)


@pytest.mark.parametrize("failure", [("W", 2, "timeout"), ("U", 5, "timeout"), ("M", 7, "timeout"),
                                     ("M", 3, "watchdog_abort"), ("U", 1, "bad_json"), ("M", 20, "nonzero_exit(1)")])
def test_any_arm_failure_is_invalid_and_never_dropped(tmp_path, failure):
    kind, index, status = failure
    runner = FakeRunner(fail={(kind, index): status})
    result = ma.execute(tmp_path, runner=runner)
    assert result["run_status"] == INVALID and result["verdict"] is None
    assert any(status in reason for reason in result["invalid_reasons"])
    total_calls = len(runner.calls)
    assert total_calls < 3 + 40 or (kind, index) == ("M", 20)


def test_analyse_rejects_incomplete_runs():
    run = {"warmups": [{"warmup": i, "status": ma.OK, "child_seconds": 2.0} for i in (1, 2, 3)],
           "iterations": 1, "pairs": [], "child_sha256": "x"}
    assert ma.analyse(run)["run_status"] == INVALID


def test_result_file_reader_handles_missing_and_bad_json(tmp_path):
    assert ma.read_result(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ma.read_result(bad) is None
    good = tmp_path / "good.json"
    good.write_text('{"child_seconds": 1.25, "child_seconds_rounded": 1.2}', encoding="utf-8")
    assert ma.read_result(good) == {"child_seconds": 1.25, "child_seconds_rounded": 1.2}


def test_every_child_program_compiles():
    from scripts.monitor_validity_v2 import children

    for name in children.CHILDREN:
        source = (children.PACKAGE_DIR / name).read_text(encoding="utf-8")
        compile(source, name, "exec")


def test_a_child_writes_a_parseable_result_file(tmp_path):
    """Mechanics only (tiny iteration count, unmonitored): not MV-02A evidence."""
    import subprocess

    from scripts.monitor_validity_v2 import children

    child, _ = children.write_child(tmp_path, children.A_WORKLOAD)
    result_file = tmp_path / "result.json"
    proc = subprocess.run([sys.executable, str(child), "--iterations", "1000", "--result-file", str(result_file)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    parsed = ma.read_result(result_file)
    assert parsed is not None and parsed["child_seconds"] > 0
