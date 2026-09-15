from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.events import Event
from core.event_log import EventLog
from core.telemetry import AgentTelemetry


def test_trace_creates_event():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            telemetry = AgentTelemetry(log)
            telemetry.trace("interaction", "tool_call", {"tool": "read_file", "session_id": "s1"})
            events = log.get_session_events("s1")
            assert len(events) == 1
            assert events[0].type == "trace.interaction"


def test_redact_api_key():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            telemetry = AgentTelemetry(log)
            telemetry.trace("security", "api_call", {"api_key": "sk-1234567890abcdef", "session_id": "s1"})
            events = log.get_session_events("s1")
            payload = events[0].payload
            assert "sk-1234567890abcdef" not in str(payload)
            assert "[REDACTED]" in str(payload)


def test_redact_private_key():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            telemetry = AgentTelemetry(log)
            telemetry.trace("security", "key_use", {"key": "-----BEGIN RSA PRIVATE KEY-----\nMIIBog\n-----END RSA PRIVATE KEY-----", "session_id": "s1"})
            events = log.get_session_events("s1")
            payload = events[0].payload
            assert "RSA PRIVATE KEY" not in str(payload)
            assert "[REDACTED]" in str(payload)
