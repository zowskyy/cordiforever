from __future__ import annotations

import pytest

from plugins.ci.ci_plugin import CIPlugin, CIRun


def test_ci_plugin_defaults():
    plugin = CIPlugin()
    assert plugin._repo is None
    assert plugin._workflow == "Long-Horizon Benchmark.yml"
    assert plugin._runs == []
    assert plugin.get_status()["status"] == "unknown"


def test_ci_plugin_get_status_with_no_runs():
    plugin = CIPlugin()
    status = plugin.get_status()
    assert status["status"] == "unknown"
    assert "No CI runs found" in status["message"]


def test_ci_run_dataclass():
    run = CIRun(run_id="12345", status="completed", conclusion="success")
    assert run.run_id == "12345"
    assert run.status == "completed"
    assert run.conclusion == "success"
    assert run.timestamp > 0
