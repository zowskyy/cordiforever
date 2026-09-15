from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.core.health_monitoring import HealthMonitoringPlugin
from plugins.core.hot_swap import HotSwapPlugin
from plugins.tools.file import FileTools


def test_hot_swap_reload_plugin(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=tmp_path)
    reg.register_class(HealthMonitoringPlugin)
    reg.register_class(HotSwapPlugin)
    reg.start_all()
    hs = ctx.plugins["hot_swap"]
    result = hs.reload_plugin(reg, "file_tools")
    assert result.success is True
    assert result.plugin == "file_tools"


def test_hot_swap_reload_unknown_plugin():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(HealthMonitoringPlugin)
    reg.register_class(HotSwapPlugin)
    reg.start_all()
    hs = ctx.plugins["hot_swap"]
    result = hs.reload_plugin(reg, "nonexistent")
    assert result.success is False
    assert "unknown" in result.message.lower()


def test_hot_swap_history():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=Path("."))
    reg.register_class(HealthMonitoringPlugin)
    reg.register_class(HotSwapPlugin)
    reg.start_all()
    hs = ctx.plugins["hot_swap"]
    hs.reload_plugin(reg, "file_tools")
    assert len(hs.get_history()) == 1
    assert hs.get_history()[0].plugin == "file_tools"
