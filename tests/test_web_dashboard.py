"""Tests for the Web Dashboard plugin."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from plugins.web.server import WebDashboard


def _make_context():
    ctx = MagicMock()
    ctx.config = {"profile": "lite"}
    ctx.plugins = {}
    ctx.events = MagicMock()
    ctx.events.emit = MagicMock()
    return ctx


def test_web_dashboard_registers_name():
    plugin = WebDashboard()
    assert plugin.name == "web_dashboard"


def test_web_dashboard_start_requires_fastapi(monkeypatch):
    plugin = WebDashboard()
    monkeypatch.setattr("plugins.web.server._FASTAPI_AVAILABLE", False)
    plugin.context = _make_context()
    plugin.start()
    assert plugin._thread is None


def test_web_dashboard_lists_sessions():
    plugin = WebDashboard()
    plugin.context = _make_context()
    event_logger = MagicMock()
    event_logger._event_log.query.return_value = [("s1",), ("s2",)]
    plugin.context.plugins["event_logger"] = event_logger
    sessions = plugin.list_sessions()
    assert [s["session_id"] for s in sessions] == ["s1", "s2"]


def test_web_dashboard_get_session_empty_when_missing():
    plugin = WebDashboard()
    plugin.context = _make_context()
    assert plugin.get_session("missing") == {"session_id": "missing", "events": []}


def test_web_dashboard_delete_session_placeholder():
    plugin = WebDashboard()
    plugin.context = _make_context()
    result = plugin.delete_session("s1")
    assert result == {"deleted": True, "session_id": "s1"}


def test_web_dashboard_metrics_empty_when_missing():
    plugin = WebDashboard()
    plugin.context = _make_context()
    assert plugin.get_metrics() == {}


def test_web_dashboard_models_empty_when_missing():
    plugin = WebDashboard()
    plugin.context = _make_context()
    assert plugin.list_models() == []


def test_web_dashboard_run_session_missing_agent():
    plugin = WebDashboard()
    plugin.context = _make_context()
    result = plugin.run_session("s1", "hello")
    assert result == {"error": "agent_loop not available"}


def test_web_dashboard_switch_model_placeholder():
    plugin = WebDashboard()
    plugin.context = _make_context()
    result = plugin.switch_model("m1", {})
    assert result == {"switched": True, "model": "m1"}
