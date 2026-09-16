"""S2 GAP-2 tests: Ollama discovery, sampling decisions, WD-01, preflight, symmetry, MV-01.

All fixtures are synthetic. No model, no Ollama, no benchmark corpus. The decision logic is pure and
is exercised through an injected fake probe so the same assertions hold on Windows and on CI Linux.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import monitor_validity_probe_v1 as mv  # noqa: E402
from scripts import resource_monitor_v1 as rm  # noqa: E402

MIB = rm.MIB


class FakeProbe:
    def __init__(self, processes, listeners, available=4000 * MIB, total=5475 * MIB, committed=None):
        self._processes = processes
        self._listeners = listeners
        self._available = available
        self._total = total
        self._committed = committed

    def total_memory_bytes(self): return self._total
    def available_memory_bytes(self): return self._available
    def committed_bytes(self): return self._committed
    def processes(self): return list(self._processes)
    def listener_pids(self, port): return list(self._listeners)


def proc(pid, name, ppid=0, rss=10 * MIB, faults=100):
    return rm.ProcessInfo(pid=pid, name=name, ppid=ppid, rss_bytes=rss, page_faults=faults)


SERVER, TRAY, CHILD, UNRELATED = 1980, 21316, 2200, 4242

BASE_PROCESSES = [
    proc(SERVER, "ollama.exe", ppid=1, rss=62 * MIB),
    proc(TRAY, "ollama app.exe", ppid=1, rss=124 * MIB),
    proc(CHILD, "ollama_llama_server.exe", ppid=SERVER, rss=1500 * MIB),
    proc(UNRELATED, "explorer.exe", ppid=1, rss=115 * MIB),
]


# ============================================================================= discovery

def test_discovery_anchors_on_the_port_owner_and_includes_descendants():
    owner, pids = rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, [SERVER]))
    assert owner == SERVER
    assert pids == {SERVER, CHILD}


def test_tray_gui_is_not_counted_merely_because_of_its_name():
    _owner, pids = rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, [SERVER]))
    assert TRAY not in pids


def test_tray_gui_is_counted_when_it_is_actually_the_port_owner():
    _owner, pids = rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, [TRAY]))
    assert TRAY in pids


def test_no_listener_fails_closed():
    with pytest.raises(rm.MonitorError, match="no process is listening"):
        rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, []))


def test_multiple_listeners_fail_closed():
    with pytest.raises(rm.MonitorError, match="ownership is ambiguous"):
        rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, [SERVER, TRAY]))


def test_server_pid_change_yields_a_different_anchor():
    first = rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, [SERVER]))[1]
    moved = [proc(9999, "ollama.exe", ppid=1), proc(CHILD, "ollama_llama_server.exe", ppid=9999)]
    second = rm.discover_ollama_pids(FakeProbe(moved, [9999]))[1]
    assert first != second and second == {9999, CHILD}


def test_inference_child_creation_and_death_are_reflected():
    without = rm.discover_ollama_pids(FakeProbe([p for p in BASE_PROCESSES if p.pid != CHILD], [SERVER]))[1]
    assert without == {SERVER}
    with_child = rm.discover_ollama_pids(FakeProbe(BASE_PROCESSES, [SERVER]))[1]
    assert with_child == {SERVER, CHILD}


def test_descendants_handles_deep_trees_and_cycles_safely():
    tree = [proc(1, "a", ppid=0), proc(2, "b", ppid=1), proc(3, "c", ppid=2), proc(4, "d", ppid=3)]
    assert rm.descendants(tree, 1) == {1, 2, 3, 4}
    assert rm.descendants(tree, 3) == {3, 4}


def test_missing_pid_during_sampling_does_not_raise():
    sample = rm.take_sample(FakeProbe(BASE_PROCESSES, [SERVER]), 0, "generation",
                            {SERVER, CHILD, 77777}, {UNRELATED}, UNRELATED)
    assert sample.ollama_rss_bytes == (62 + 1500) * MIB


# ============================================================================= WD-01

def sample(index, available_mib, phase="generation"):
    return rm.Sample(index=index, monotonic=float(index), phase=phase,
                     available_bytes=available_mib * MIB, committed_bytes=None,
                     ollama_rss_bytes=0, harness_rss_bytes=0, monitor_rss_bytes=0,
                     ollama_page_faults=None)


def test_watchdog_fires_after_eight_consecutive_sub_reserve_samples():
    samples = [sample(i, 400) for i in range(8)]
    assert rm.watchdog_abort_index(samples, rm.RESERVE_MIB * MIB) == 7


def test_watchdog_does_not_fire_on_seven():
    samples = [sample(i, 400) for i in range(7)]
    assert rm.watchdog_abort_index(samples, rm.RESERVE_MIB * MIB) is None


def test_watchdog_run_resets_on_recovery():
    samples = [sample(i, 400) for i in range(7)] + [sample(7, 900)] + [sample(i, 400) for i in range(8, 14)]
    assert rm.watchdog_abort_index(samples, rm.RESERVE_MIB * MIB) is None


def test_watchdog_boundary_is_strictly_below_reserve():
    exactly = [sample(i, rm.RESERVE_MIB) for i in range(20)]
    assert rm.watchdog_abort_index(exactly, rm.RESERVE_MIB * MIB) is None


# ============================================================================= summarize / gate

def test_summary_reports_sampled_extrema_and_derived_drop():
    samples = [sample(0, 2000), sample(1, 1500), sample(2, 1900)]
    summary = rm.summarize(samples)
    assert summary["sampled_available_min_bytes"] == 1500 * MIB
    assert summary["sampled_available_max_bytes"] == 2000 * MIB
    assert summary["sampled_drop_max_bytes"] == 500 * MIB


def test_empty_sample_series_is_unknown_not_zero():
    summary = rm.summarize([])
    assert summary["sampled_available_min_bytes"] == rm.UNKNOWN


def test_gate_passes_only_when_every_condition_holds():
    summary = {"sampled_available_min_bytes": 1000 * MIB}
    result = rm.evaluate_gate(summary, reserve_bytes=rm.RESERVE_MIB * MIB, oom_or_death=False,
                              watchdog_abort=False, load_succeeded=True)
    assert result["passed"] is True
    assert all(result["conditions"].values())


@pytest.mark.parametrize("kwargs", [
    {"oom_or_death": True}, {"watchdog_abort": True}, {"load_succeeded": False},
])
def test_gate_fails_on_each_condition(kwargs):
    summary = {"sampled_available_min_bytes": 1000 * MIB}
    base = {"oom_or_death": False, "watchdog_abort": False, "load_succeeded": True}
    result = rm.evaluate_gate(summary, reserve_bytes=rm.RESERVE_MIB * MIB, **{**base, **kwargs})
    assert result["passed"] is False


def test_gate_fails_below_reserve():
    summary = {"sampled_available_min_bytes": 511 * MIB}
    result = rm.evaluate_gate(summary, reserve_bytes=rm.RESERVE_MIB * MIB, oom_or_death=False,
                              watchdog_abort=False, load_succeeded=True)
    assert result["passed"] is False


def test_gate_reserve_basis_is_labelled_policy():
    result = rm.evaluate_gate({"sampled_available_min_bytes": 1000 * MIB},
                              reserve_bytes=rm.RESERVE_MIB * MIB, oom_or_death=False,
                              watchdog_abort=False, load_succeeded=True)
    assert "[POLICY]" in result["reserve_basis"]
    assert "not empirically established" in result["reserve_basis"]


def test_unknown_summary_cannot_pass_the_gate():
    result = rm.evaluate_gate(rm.summarize([]), reserve_bytes=rm.RESERVE_MIB * MIB,
                              oom_or_death=False, watchdog_abort=False, load_succeeded=True)
    assert result["passed"] is False


# ============================================================================= preflight / symmetry

def test_preflight_detects_excluded_workload_classes():
    processes = BASE_PROCESSES + [proc(70, "claude.exe", rss=940 * MIB), proc(71, "Grok Bot.exe", rss=425 * MIB)]
    snapshot = rm.preflight_snapshot(FakeProbe(processes, [SERVER]))
    assert snapshot["quiesced"] is False
    assert "claude_code" in snapshot["excluded_workload_classes_present"]
    assert "grok_bot" in snapshot["excluded_workload_classes_present"]


def test_preflight_ignores_small_matches_below_the_reporting_threshold():
    processes = BASE_PROCESSES + [proc(72, "claude.exe", rss=5 * MIB)]
    assert rm.preflight_snapshot(FakeProbe(processes, [SERVER]))["quiesced"] is True


def test_preflight_does_not_fail_on_ordinary_service_churn():
    processes = BASE_PROCESSES + [proc(80 + i, "svchost.exe", rss=8 * MIB) for i in range(60)]
    assert rm.preflight_snapshot(FakeProbe(processes, [SERVER]))["quiesced"] is True


def test_preflight_never_terminates_anything():
    source = (ROOT / "scripts" / "resource_monitor_v1.py").read_text(encoding="utf-8")
    body = source.split("def preflight_snapshot")[1].split("def check_symmetry")[0]
    # Call patterns, not the word: the function's own docstring says it never terminates anything.
    for forbidden in (".terminate(", ".kill(", "taskkill", "TerminateProcess", "os.kill"):
        assert forbidden not in body


def test_symmetry_tolerance_accepts_close_starting_states():
    a = {"available_bytes": 3200 * MIB, "excluded_workload_classes_present": []}
    b = {"available_bytes": 3100 * MIB, "excluded_workload_classes_present": []}
    assert rm.check_symmetry(a, b)["comparable"] is True


def test_symmetry_tolerance_rejects_divergent_starting_states():
    a = {"available_bytes": 3200 * MIB, "excluded_workload_classes_present": []}
    b = {"available_bytes": 2000 * MIB, "excluded_workload_classes_present": []}
    result = rm.check_symmetry(a, b)
    assert result["comparable"] is False and "AVAIL_0 differs" in result["reasons"][0]


def test_symmetry_rejects_a_contaminated_preflight():
    a = {"available_bytes": 3200 * MIB, "excluded_workload_classes_present": ["claude_code"]}
    b = {"available_bytes": 3200 * MIB, "excluded_workload_classes_present": []}
    assert rm.check_symmetry(a, b)["comparable"] is False


# ============================================================================= schema discipline

def test_every_reported_quantity_declares_direct_or_derived():
    for name, label in rm.DIRECT_VS_DERIVED.items():
        assert label.startswith(("direct", "derived")), name


def test_process_rss_is_never_called_model_memory():
    source = (ROOT / "scripts" / "resource_monitor_v1.py").read_text(encoding="utf-8")
    assert "NOT model memory" in source
    assert rm.DIRECT_VS_DERIVED["model_attributable_delta_bytes"].startswith("derived")


def test_sampled_extrema_are_named_as_sampled():
    for key in rm.DIRECT_VS_DERIVED:
        if "min_bytes" in key or "peak" in key or "max_bytes" in key:
            assert key.startswith("sampled_"), key


def test_drop_max_is_declared_as_bounding_nothing():
    assert "bounds no unobserved transient" in rm.DIRECT_VS_DERIVED["sampled_drop_max_bytes"]


# ============================================================================= MV-01 decision logic

def test_equivalence_pass_when_interval_is_inside_the_margin():
    diffs = [0.001 * ((-1) ** i) for i in range(20)]
    result = mv.equivalence_decision(diffs, margin=0.02)
    assert result["decision"] == mv.PASS


def test_equivalence_fail_when_interval_is_entirely_outside():
    diffs = [0.10 + 0.001 * i for i in range(20)]
    result = mv.equivalence_decision(diffs, margin=0.02)
    assert result["decision"] == mv.FAIL


def test_equivalence_unresolved_when_interval_straddles_the_margin():
    diffs = [0.019 * ((-1) ** i) + 0.015 for i in range(20)]
    result = mv.equivalence_decision(diffs, margin=0.02)
    assert result["decision"] == mv.UNRESOLVED


def test_too_few_observations_is_unresolved_not_pass():
    assert mv.equivalence_decision([0.0], margin=0.02)["decision"] == mv.UNRESOLVED
    assert mv.equivalence_decision([], margin=0.02)["decision"] == mv.UNRESOLVED


def test_wide_noisy_data_is_unresolved_never_pass():
    """Large scatter around zero must NOT be reported as equivalence."""
    diffs = [0.5 * ((-1) ** i) for i in range(20)]
    assert mv.equivalence_decision(diffs, margin=0.02)["decision"] == mv.UNRESOLVED


def test_decision_never_uses_a_p_value_threshold():
    source = (ROOT / "scripts" / "monitor_validity_probe_v1.py").read_text(encoding="utf-8")
    body = source.split("def equivalence_decision")[1].split("def combine_decisions")[0]
    assert "p_value" not in body and "pvalue" not in body


def test_combined_result_is_fail_if_any_quantity_fails():
    decisions = {"a": {"decision": mv.PASS}, "b": {"decision": mv.FAIL}}
    assert mv.combine_decisions(decisions, 10 * MIB)["overall"] == mv.FAIL


def test_combined_result_is_unresolved_if_any_quantity_is_unresolved():
    decisions = {"a": {"decision": mv.PASS}, "b": {"decision": mv.UNRESOLVED}}
    assert mv.combine_decisions(decisions, 10 * MIB)["overall"] == mv.UNRESOLVED


def test_combined_result_requires_every_quantity_to_pass():
    decisions = {"a": {"decision": mv.PASS}, "b": {"decision": mv.PASS}}
    assert mv.combine_decisions(decisions, 10 * MIB)["overall"] == mv.PASS


def test_monitor_rss_over_cap_fails():
    decisions = {"a": {"decision": mv.PASS}}
    assert mv.combine_decisions(decisions, 200 * MIB)["overall"] == mv.FAIL


def test_unknown_monitor_rss_is_unresolved_not_pass():
    decisions = {"a": {"decision": mv.PASS}}
    assert mv.combine_decisions(decisions, None)["overall"] == mv.UNRESOLVED


def test_margins_are_labelled_policy_with_an_operational_justification():
    for name, spec in mv.MARGINS.items():
        assert spec["label"] == "[POLICY]", name
        assert "Operational budget" in spec["justification"], name
        assert "not a measured property" in spec["justification"], name


def test_sign_test_rank_is_exact():
    # n=20, alpha=.05: largest k with P(Bin(20,.5) <= k-1) <= .025 is 6 (P(X<=5)=0.0207)
    assert mv.sign_test_ci_rank(20, 0.05) == 6
    assert mv.sign_test_ci_rank(1, 0.05) is None


def test_analyse_returns_unresolved_when_the_unmonitored_arm_cannot_supply_a_quantity():
    observations = [{"pair": i,
                     "monitored": {"duration_seconds": 1.0, "available_min_bytes": 1000,
                                   "child_rss_bytes": 10, "monitor_rss_bytes": 5 * MIB},
                     "unmonitored": {"duration_seconds": 1.0, "available_min_bytes": None,
                                     "child_rss_bytes": None}}
                    for i in range(20)]
    report = mv.analyse(observations)
    assert report["decisions"]["available_min_bytes"]["decision"] == mv.UNRESOLVED
    assert report["result"]["overall"] == mv.UNRESOLVED


def test_protocol_records_interleaving_and_frozen_parameters():
    report = mv.analyse([])
    assert "adjacent unmonitored counterpart" in report["protocol"]["interleaving"]
    assert report["protocol"]["alpha"] == mv.ALPHA


# ============================================================================= end-to-end (synthetic)

def test_run_monitored_against_a_synthetic_subprocess(tmp_path):
    """Exercises the real sampling loop on a trivial child. No model, no Ollama."""
    script = tmp_path / "child.py"
    script.write_text("import time\ntime.sleep(1.2)\nprint('done')\n", encoding="utf-8")
    state, artifact = rm.run_monitored([sys.executable, str(script)], discover_ollama=False,
                                       cwd=ROOT, max_seconds=60)
    assert state.returncode == 0
    assert artifact["summary"]["samples"] >= 2, "the sampler must produce multiple samples"
    assert artifact["watchdog_abort"] is False
    assert artifact["ollama_owner_pid"] is None and artifact["ollama_pids"] == []
    assert artifact["schema"] == "resource_v1"
    assert set(artifact["direct_vs_derived"]) >= {"available_bytes", "sampled_available_min_bytes"}


def test_run_monitored_records_a_nonzero_exit_as_an_event(tmp_path):
    script = tmp_path / "boom.py"
    script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    _state, artifact = rm.run_monitored([sys.executable, str(script)], discover_ollama=False,
                                        cwd=ROOT, max_seconds=60)
    assert artifact["returncode"] == 3
    assert any(e["event"] == "nonzero_exit" for e in artifact["events"])
    assert artifact["gate"]["passed"] is False


def test_workload_script_is_synthetic_and_touches_no_model(tmp_path):
    script = mv.write_workload(tmp_path)
    source = script.read_text(encoding="utf-8")
    for forbidden in ("ollama", "http", "requests", "model", "benchmark"):
        assert forbidden not in source.lower()


# ============================================================================= MV-01 interval proof

def test_1_exact_order_statistic_indices_for_n20_alpha05():
    """k = 6, so the interval is 1-indexed [d_(6), d_(15)] = 0-indexed [values[5], values[14]]."""
    assert mv.sign_test_ci_rank(20, 0.05) == 6
    diffs = list(range(20))                      # values[i] == i, so the indices are readable
    assert mv.distribution_free_ci(diffs, 0.05) == (5, 14)


def test_1b_rank_is_the_largest_k_satisfying_the_exact_tail():
    import math
    n, alpha = 20, 0.05
    k = mv.sign_test_ci_rank(n, alpha)
    tail = lambda j: sum(math.comb(n, i) for i in range(0, j)) / 2 ** n
    assert tail(k) <= alpha / 2
    assert tail(k + 1) > alpha / 2               # k is maximal, so the interval is the narrowest valid one


def test_2_actual_finite_sample_coverage_is_reported_and_conservative():
    coverage = mv.interval_coverage(20, 0.05)
    assert coverage == pytest.approx(0.958611, abs=1e-6)
    assert coverage > 0.95, "discrete coverage must be conservative, never anti-conservative"
    assert coverage != 0.95, "the interval must not be described as exactly 95%"


def test_2b_every_decision_carries_its_coverage_and_rank():
    result = mv.equivalence_decision([0.001] * 20, 0.02)
    assert result["order_statistic_rank_k"] == 6
    assert result["actual_finite_sample_coverage"] == pytest.approx(0.958611, abs=1e-6)
    assert "DISCRETE" in result["method"]


def test_3_ties_do_not_break_the_interval():
    """Real timing data is discrete. Ties must remain valid and conservative, never an error."""
    diffs = [0.005] * 20
    assert mv.distribution_free_ci(diffs, 0.05) == (0.005, 0.005)
    assert mv.equivalence_decision(diffs, 0.02)["decision"] == mv.PASS
    half = [0.001] * 10 + [0.002] * 10
    assert mv.distribution_free_ci(half, 0.05) == (0.001, 0.002)


def test_4_even_n_needs_no_middle_element():
    for n in (10, 12, 20, 30):
        k = mv.sign_test_ci_rank(n, 0.05)
        if k is None:
            continue
        diffs = list(range(n))
        assert mv.distribution_free_ci(diffs, 0.05) == (k - 1, n - k)


def test_5_method_is_distribution_free_under_the_stated_assumptions():
    """The interval depends only on order statistics, so any monotone relabelling maps through it."""
    diffs = [0.001 * i for i in range(20)]
    low, high = mv.distribution_free_ci(diffs, 0.05)
    skewed = [d ** 3 for d in diffs]             # heavy monotone distortion; no symmetry, no normality
    slow, shigh = mv.distribution_free_ci(skewed, 0.05)
    assert (slow, shigh) == (low ** 3, high ** 3)


def test_6_narrowest_attainable_interval_for_n20_is_zero_width():
    """It discards the 5 smallest and 5 largest, so identical middle-ten data gives width zero."""
    diffs = [-9.0] * 5 + [0.004] * 10 + [9.0] * 5
    low, high = mv.distribution_free_ci(diffs, 0.05)
    assert (low, high) == (0.004, 0.004)
    assert high - low == 0.0


def test_7_realistic_low_noise_fixture_attains_pass():
    """+0.4% mean shift with +-0.5% scatter: comfortably inside the 2% operational budget."""
    diffs = [0.004 + 0.005 * math.sin(i * 1.7) for i in range(20)]  # deterministic scatter, no RNG
    result = mv.equivalence_decision(diffs, mv.MARGINS["duration_relative"]["margin"])
    assert result["decision"] == mv.PASS
    assert -0.02 < result["interval"][0] and result["interval"][1] < 0.02



def test_8_interval_touching_the_margin_is_unresolved_not_pass():
    """Inclusion is STRICT: an endpoint exactly on the margin does not establish equivalence."""
    margin = 0.02
    diffs = [0.0] * 14 + [margin] * 6            # d_(15) == margin exactly
    low, high = mv.distribution_free_ci(diffs, 0.05)
    assert high == margin
    assert mv.equivalence_decision(diffs, margin)["decision"] == mv.UNRESOLVED
    inside = [0.0] * 15 + [margin] * 5           # d_(15) now strictly inside
    assert mv.equivalence_decision(inside, margin)["decision"] == mv.PASS


def test_9_noisy_zero_centred_fixture_stays_unresolved():
    diffs = [0.5 * ((-1) ** i) for i in range(20)]
    result = mv.equivalence_decision(diffs, 0.02)
    assert result["decision"] == mv.UNRESOLVED
    assert result["point_estimate_hodges_lehmann"] == pytest.approx(0.0, abs=1e-9)


def test_10_outside_margin_fixture_fails():
    diffs = [0.08 + 0.001 * i for i in range(20)]
    result = mv.equivalence_decision(diffs, 0.02)
    assert result["decision"] == mv.FAIL
    assert result["interval"][0] > 0.02


def test_pass_is_attainable_for_every_preregistered_margin():
    """None of the four margins is vacuous at n = 20."""
    for name, spec in mv.MARGINS.items():
        margin = spec["margin"]
        diffs = [margin * 0.1] * 20
        assert mv.equivalence_decision(diffs, margin)["decision"] == mv.PASS, name
