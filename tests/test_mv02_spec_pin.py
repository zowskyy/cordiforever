"""The implementation is pinned to the frozen MV-02 v2.1 specification bytes and its threshold ledger."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import monitor_validity_v2 as mv02  # noqa: E402
from scripts.monitor_validity_v2 import mv02a_perturbation as ma  # noqa: E402
from scripts.monitor_validity_v2 import mv02b_measurement as mb  # noqa: E402
from scripts.monitor_validity_v2 import mv02c_enforcement as mc  # noqa: E402

SPEC_BYTES = mv02.SPEC_PATH.read_bytes()
SPEC = SPEC_BYTES.decode("utf-8")
MIB = 1024 * 1024


def test_spec_bytes_are_the_frozen_v2_1_specification():
    assert hashlib.sha256(SPEC_BYTES).hexdigest() == mv02.SPEC_SHA256 == \
        "e14b533363bee0bc946e6dfddbbfc516b1b195be3dbbbb8d75644c17eb0ae585"
    assert hashlib.sha256(mv02.MONITOR_V1_PATH.read_bytes()).hexdigest() == mv02.MONITOR_V1_SHA256


def test_a_thresholds_match_the_ledger():
    assert "| A tolerance | ±0.02 |" in SPEC and ma.FROZEN_A["tolerance_relative"] == 0.02
    assert "| A n / alpha / k / coverage | 20 / 0.05 / 6 / 0.958611 |" in SPEC
    assert (ma.FROZEN_A["pairs"], ma.FROZEN_A["alpha"]) == (20, 0.05)
    assert "| A target duration | 8.0 | s |" in SPEC and ma.FROZEN_A["target_duration_s"] == 8.0
    assert "| A warm-up rule | 3 runs, I0 = 10,000,000, rescale to target |" in SPEC
    assert (ma.FROZEN_A["warmups"], ma.FROZEN_A["warmup_iterations"]) == (3, 10_000_000)
    assert "| A timeout (warm-ups, M max_seconds, U timeout) | 120 | s |" in SPEC and ma.FROZEN_A["timeout_s"] == 120


def test_b_thresholds_match_the_ledger():
    assert "| T (B1 tolerance) | 16 | MiB |" in SPEC and mb.FROZEN_B["t_bytes"] == 16 * MIB
    assert "| B2 tolerance | 32 (2T) | MiB |" in SPEC and mb.FROZEN_B["b2_bytes"] == 32 * MIB
    assert "| X_target / X_min | 144 / 80 | MiB |" in SPEC
    assert (mb.FROZEN_B["x_target_mib"], mb.FROZEN_B["x_min_mib"]) == (144, 80)
    assert "| H | 512 | MiB |" in SPEC and mb.FROZEN_B["headroom_mib"] == 512
    assert "| O | 128 | MiB |" in SPEC and mb.FROZEN_B["overhead_mib"] == 128
    assert "A0 >= X + 1152 (1296 for 144; 1232 for 80)" in SPEC and mb.FROZEN_B["required_free_mib"] == 1152
    assert "| Hold / G / min in-window samples | 3.0 s / 0.5 s / 4 per hold |" in SPEC
    assert (mb.FROZEN_B["alloc_hold_s"], mb.FROZEN_B["guard_band_s"], mb.FROZEN_B["min_in_window_samples"]) == \
        (3.0, 0.5, 4)
    assert "/ 10 / 0.05 / 2 / 0.978515625 (reported 0.978516) |" in SPEC
    assert (mb.FROZEN_B["n_required"], mb.FROZEN_B["invocations"]) == (10, 10)
    assert "| B timeout (max_seconds per invocation) | 120 | s |" in SPEC and mb.FROZEN_B["max_seconds"] == 120
    assert "| B3 span bound | 3.5 s per 8-sample window, within each invocation only | s |" in SPEC
    assert (mb.FROZEN_B["b3_window_samples"], mb.FROZEN_B["b3_max_span_s"]) == (8, 3.5)
    assert "every 250 ms by its own clock" in SPEC.lower() and mb.FROZEN_B["child_sample_interval_s"] == 0.25


def test_c_policy_matches_the_ledger():
    assert "| C timeout (max_seconds) | 30 | s |" in SPEC and mc.C_MAX_SECONDS == 30
    assert "call 5 begins sample index 2" in SPEC and next(c for c in mc.CASES if c.case_id == "C9").fault_call == 5
