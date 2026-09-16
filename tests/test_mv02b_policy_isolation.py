"""The MV-02B evidence executor owns the frozen policy and cannot inherit smoke-test parameters."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import mv02b_measurement as mb  # noqa: E402
from scripts.monitor_validity_v2 import smoke_b_child as smoke  # noqa: E402

MIB = 1024 * 1024


def test_frozen_policy_matches_the_specification():
    assert mb.FROZEN_B["invocations"] == 10
    assert mb.FROZEN_B["baseline_hold_s"] == mb.FROZEN_B["alloc_hold_s"] == mb.FROZEN_B["final_hold_s"] == 3.0
    assert mb.FROZEN_B["child_sample_interval_s"] == 0.25
    assert mb.FROZEN_B["guard_band_s"] == 0.5
    assert mb.FROZEN_B["min_in_window_samples"] == 4
    assert mb.FROZEN_B["t_bytes"] == 16 * MIB and mb.FROZEN_B["b2_bytes"] == 32 * MIB
    assert (mb.FROZEN_B["x_target_mib"], mb.FROZEN_B["x_min_mib"]) == (144, 80)
    assert mb.FROZEN_B["required_free_mib"] == (mb.FROZEN_B["reserve_mib"] + mb.FROZEN_B["headroom_mib"]
                                                + mb.FROZEN_B["overhead_mib"]) == 1152
    assert mb.FROZEN_B["max_seconds"] == 120
    assert (mb.FROZEN_B["n_required"], mb.FROZEN_B["alpha"]) == (10, 0.05)
    assert (mb.FROZEN_B["b3_window_samples"], mb.FROZEN_B["b3_max_span_s"]) == (8, 3.5)


def test_executor_accepts_no_policy_parameters():
    parameters = inspect.signature(mb.execute).parameters
    assert list(parameters) == ["scratch", "monitor_runner", "child_factory"]
    assert list(inspect.signature(mb.build_command).parameters) == ["child", "sidecar", "invocation", "fixed_x_mib"]


def _value(command, flag):
    return command[command.index(flag) + 1]


def test_every_evidence_command_carries_the_frozen_configuration():
    first = mb.build_command(Path("c.py"), Path("s.jsonl"), invocation=1, fixed_x_mib=None)
    later = mb.build_command(Path("c.py"), Path("s.jsonl"), invocation=7, fixed_x_mib=80)
    for command in (first, later):
        assert _value(command, "--baseline-hold") == _value(command, "--alloc-hold") == \
            _value(command, "--final-hold") == "3.0"
        assert _value(command, "--sample-interval") == "0.25"
        assert _value(command, "--required-free-mib") == "1152"
        assert "--alloc-mib" not in command
    assert "--select-x" in first and _value(first, "--x-target-mib") == "144" and _value(first, "--x-min-mib") == "80"
    assert _value(later, "--fixed-x") == "80" and "--select-x" not in later


def test_smoke_parameters_never_reach_the_evidence_executor():
    assert smoke.SMOKE_ALLOC_MIB == 16
    assert smoke.SMOKE_LABEL == "B CHILD SMOKE — ENGINEERING ONLY — NOT MV-02 EVIDENCE"
    source = inspect.getsource(mb)
    assert "smoke" not in source.lower()
    smoke_command = smoke.build_smoke_command(Path("c.py"), Path("s.jsonl"))
    assert _value(smoke_command, "--alloc-mib") == "16"
    assert "--select-x" not in smoke_command and "--fixed-x" not in smoke_command


def test_smoke_refuses_evidence_locations(tmp_path):
    for bad in (ROOT / "benchmark" / "analysis" / "output_mv02" / "x.json",
                tmp_path / "cordii-qualification-2026-09-17" / "x.json"):
        try:
            smoke.check_output_path(bad)
        except ValueError:
            continue
        raise AssertionError(f"smoke accepted evidence path {bad}")
    smoke.check_output_path(tmp_path / "smoke" / "report.json")
