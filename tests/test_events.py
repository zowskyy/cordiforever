from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.continuity import Continuity
from core.event_log import EventLog
from core.events import Event


def test_event_roundtrip():
    event = Event(
        type="user.message",
        session_id="s1",
        payload={"content": "hello"},
        task_id="t1",
        parent_event_id=1,
        operation_id="op1",
    )
    data = event.to_dict()
    assert data["type"] == "user.message"
    assert data["session_id"] == "s1"
    assert data["payload"] == {"content": "hello"}


def test_event_from_row():
    row = (
        1,
        "2025-01-01T00:00:00Z",
        "tool.call",
        "s1",
        "t1",
        None,
        "op1",
        json.dumps({"tool": "read_file"}),
    )
    event = Event.from_row(row)
    assert event.id == 1
    assert event.type == "tool.call"
    assert event.payload == {"tool": "read_file"}


def test_event_default_timestamp_is_utc():
    event = Event(type="test", session_id="s1", payload={})
    assert "Z" in event.timestamp
