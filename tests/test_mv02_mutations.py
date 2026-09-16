"""Structural checks for the MV-02 mutation definitions (the runner itself executes in scratch processes)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import mutations as mut  # noqa: E402


def test_every_anchor_occurs_exactly_once_and_the_mutant_compiles():
    for mutation in mut.MUTATIONS:
        source = mut.source_path(mutation).read_text(encoding="utf-8")
        mutated = mut.mutated_source(mutation)
        assert mutated != source, mutation["name"]
        compile(mutated, str(mut.source_path(mutation)), "exec")


def test_definitions_are_well_formed():
    names = [m["name"] for m in mut.MUTATIONS]
    assert len(names) == len(set(names))
    for mutation in mut.MUTATIONS:
        assert mutation["expected"] == "caught"
        assert mutation["group"] in ("local", "v1")
        if mutation["group"] == "local":
            assert mutation["suites"] and all((ROOT / suite).is_file() for suite in mutation["suites"])
        else:
            assert mutation["target_case"] in {"C3", "C5", "C6"} and mutation["file"] == "../resource_monitor_v1.py"


def test_required_protections_are_present():
    required = {
        "a_swap_monitored_and_unmonitored", "a_gate_on_wrapper_time", "a_silently_drop_invalid_arms",
        "a_zero_based_parity", "stats_non_strict_inclusion", "b_reference_omits_launcher", "b_guard_band_zero",
        "b_child_no_page_touch", "b2_tolerance_is_t", "b_x_reselected_every_invocation", "b_extra_invocation_added",
        "b3_windows_cross_invocations", "b_executor_accepts_policy_overrides", "c_accept_silent_death_with_gate_pass",
        "c_ignore_excepthook_records", "c_invalid_conditions_not_marked", "c9_fault_at_call_3", "c2_expected_gate_pass",
        "combine_unresolved_as_qualified", "combine_invalid_as_unresolved", "combine_c_fail_does_not_stop",
        "v1_watchdog_streak_7", "v1_watchdog_boundary_le", "v1_watchdog_streak_not_reset",
    }
    assert required <= {m["name"] for m in mut.MUTATIONS}


def test_mutating_never_touches_files_on_disk():
    before = {m["file"]: mut.source_path(m).read_bytes() for m in mut.MUTATIONS}
    for mutation in mut.MUTATIONS:
        mut.mutated_source(mutation)
    assert before == {m["file"]: mut.source_path(m).read_bytes() for m in mut.MUTATIONS}


def test_v1_mutations_refuse_to_run_outside_github_actions(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert mut.run("v1", None) == 5
    assert mut.run(None, "v1_watchdog_streak_7") == 5
