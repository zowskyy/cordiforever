"""Vacuity/observability audit (spec v2.1 §8): every gate metric has a producer in its declared arm or reference,
and descriptive metrics never feed a verdict."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import run_all  # noqa: E402
from tests.mv02_fixtures import FakeRunner, SyntheticB  # noqa: E402
from tests.test_mv02_combined_reachability import c_runner, child_factory  # noqa: E402

# metric -> (component, path into the component result, arm/reference)
GATE_METRICS = {
    "A relative difference": ("A", ("relative", "interval"), "both arms: M and U child-internal perf_counter"),
    "B1 attribution error": ("B", ("b1", "interval"), "monitor vs reference tree, per invocation"),
    "B2 step error": ("B", ("b2", "interval"), "monitor vs reference tree, per invocation"),
    "B3 pace": ("B", ("b3", "max_span_s"), "monitor sample timestamps within each invocation"),
}


def _dig(document, path):
    for key in path:
        document = document[key]
    return document


def _qualified(tmp_path, **kwargs):
    return run_all.run_all(tmp_path / "attempt", c_case_runner=c_runner(), b_monitor_runner=kwargs.get("b", SyntheticB()),
                           b_child_factory=child_factory, a_runner=kwargs.get("a", FakeRunner()))


def test_every_gate_metric_is_produced_on_the_real_execute_schema(tmp_path):
    result = _qualified(tmp_path)
    for metric, (component, path, _arm) in GATE_METRICS.items():
        assert _dig(result[component], path) is not None, metric
    for pair in result["A"]["pairs"]:
        assert pair["M"]["child_seconds"] is not None and pair["U"]["child_seconds"] is not None
    for invocation in result["B"]["invocations"]:
        assert invocation["b1_error"] is not None and invocation["b2_error"] is not None
    assert all(record["classification"] is not None for record in result["C"]["cases"])


def test_descriptive_metrics_never_feed_a_verdict(tmp_path):
    baseline = _qualified(tmp_path / "base")["combined"]

    class WrapperHeavy(FakeRunner):
        def monitored(self, command, max_seconds):
            result = super().monitored(command, max_seconds)
            return {**result, "wrapper_seconds": 999.0}

    class AvailShift(SyntheticB):
        def __call__(self, command):
            observed = super().__call__(command)
            for sample in observed["samples"]:
                sample["available_bytes"] = 1
            return observed

    shifted = _qualified(tmp_path / "shift", a=WrapperHeavy(), b=AvailShift())["combined"]
    assert shifted == baseline
