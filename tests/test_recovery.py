from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.context import Context
from core.event_log import EventLog
from core.events import Event
from core.recovery import RecoveryManager


def test_wake_after_tool_invoked_allows_retry():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="tool.invoked", session_id="test", payload={"call_id": "call_123", "tool_name": "file_read"}))
            rec = RecoveryManager(log)
            action = rec.wake("test")
            assert action.action == "retry_tool"
            assert action.payload["call_id"] == "call_123"


def test_wake_after_gen_sent_is_not_recoverable():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="gen.sent", session_id="test", payload={"content": "delivered"}))
            rec = RecoveryManager(log)
            action = rec.wake("test")
            assert action.action == "fail"


def test_wake_after_user_message_steps():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="test", payload={"text": "hi"}))
            rec = RecoveryManager(log)
            assert rec.wake("test").action == "step"


def test_wake_after_tool_result_steps():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="tool.result", session_id="test", payload={"success": True}))
            rec = RecoveryManager(log)
            assert rec.wake("test").action == "step"


def test_wake_non_idempotent_tool_fails():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="tool.invoked", session_id="test", payload={"call_id": "c1", "tool_name": "http_post"}))
            rec = RecoveryManager(log)
            assert rec.wake("test").action == "fail"


def test_wake_missing_call_id_fails():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="tool.invoked", session_id="test", payload={"tool_name": "file_read"}))
            rec = RecoveryManager(log)
            assert rec.wake("test").action == "fail"
