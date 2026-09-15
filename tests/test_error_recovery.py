from __future__ import annotations

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.core.error_recovery import ErrorRecoveryPlugin, RecoveryAction
from plugins.core.event_logger import EventLogger
from plugins.core.health_monitoring import HealthMonitoringPlugin


def test_error_recovery_retry_then_escalate(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(EventLogger, db_path=tmp_path / "test.db")
    reg.register_class(HealthMonitoringPlugin)
    reg.register_class(ErrorRecoveryPlugin)
    reg.start_all()
    er = ctx.plugins["error_recovery"]
    action = er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    assert action.action == "retry"
    assert action.payload["delay"] > 0
    action = er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    assert action.action == "retry"
    action = er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    assert action.action == "retry"
    action = er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    assert action.action == "fallback"
    action = er.handle_failure("permission_denied", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    assert action.action == "escalate"


def test_error_recovery_argument_aware_keys(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(EventLogger, db_path=tmp_path / "test.db")
    reg.register_class(HealthMonitoringPlugin)
    reg.register_class(ErrorRecoveryPlugin)
    reg.start_all()
    er = ctx.plugins["error_recovery"]
    er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "b.txt"}})
    assert er._make_key("write_file", {"path": "a.txt"}) != er._make_key("write_file", {"path": "b.txt"})


def test_error_recovery_reset(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(EventLogger, db_path=tmp_path / "test.db")
    reg.register_class(HealthMonitoringPlugin)
    reg.register_class(ErrorRecoveryPlugin)
    reg.start_all()
    er = ctx.plugins["error_recovery"]
    er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    er.reset("write_file", {"path": "a.txt"})
    action = er.handle_failure("timeout", {"tool_name": "write_file", "arguments": {"path": "a.txt"}})
    assert action.payload["attempt"] == 1
