from __future__ import annotations

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.core.metrics import MetricsPlugin


def test_metrics_increment_counter():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MetricsPlugin)
    reg.start_all()
    metrics = ctx.plugins["metrics"]
    metrics.increment("test_plugin", "requests", 1)
    m = metrics.get_metrics("test_plugin")
    assert m.counters["requests"] == 1


def test_metrics_record_timer():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MetricsPlugin)
    reg.start_all()
    metrics = ctx.plugins["metrics"]
    metrics.record_timer("test_plugin", "latency", 42.5)
    m = metrics.get_metrics("test_plugin")
    assert m.timers["latency"] == 42.5


def test_metrics_on_tool_result():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MetricsPlugin)
    reg.start_all()
    metrics = ctx.plugins["metrics"]
    event = type("Event", (), {"payload": {"tool": "write_file", "success": True}})()
    metrics.on_tool_result(event)
    m = metrics.get_metrics("write_file")
    assert m.counters["success_count"] == 1


def test_metrics_get_all():
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(MetricsPlugin)
    reg.start_all()
    metrics = ctx.plugins["metrics"]
    metrics.increment("a", "x", 1)
    metrics.increment("b", "y", 2)
    all_m = metrics.get_all_metrics()
    assert "a" in all_m
    assert "b" in all_m
