from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.core.health_monitoring import HealthMonitoringPlugin
from plugins.tools.file import FileTools


def test_health_monitoring_register_and_check(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=tmp_path)
    reg.register_class(HealthMonitoringPlugin)
    reg.start_all()
    hm = ctx.plugins["health_monitoring"]
    hm.register_plugin("file_tools")
    results = hm.check_all()
    assert "file_tools" in results
    assert results["file_tools"].healthy is True


def test_health_monitoring_missing_health_method():
    ctx = Context()
    reg = PluginRegistry(ctx)

    class UnhealthyPlugin(Plugin):
        name = "unhealthy"

        def health(self):
            return {"healthy": False, "message": "intentionally unhealthy"}

    reg.register_class(UnhealthyPlugin)
    reg.register_class(HealthMonitoringPlugin)
    reg.start_all()
    hm = ctx.plugins["health_monitoring"]
    hm.register_plugin("unhealthy")
    results = hm.check_all()
    assert results["unhealthy"].healthy is False
    assert "intentionally unhealthy" in results["unhealthy"].message


def test_health_monitoring_bounded_event_log():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(HealthMonitoringPlugin)
    reg.start_all()
    hm = ctx.plugins["health_monitoring"]
    for _ in range(2000):
        hm._log_event({"event": "test", "timestamp": 0.0})
    assert len(hm._event_log) <= 1000


def test_health_monitoring_system_healthy():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=Path("."))
    reg.register_class(HealthMonitoringPlugin)
    reg.start_all()
    hm = ctx.plugins["health_monitoring"]
    hm.register_plugin("file_tools")
    assert hm.system_healthy(["file_tools"]) is True
