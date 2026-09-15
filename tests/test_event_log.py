from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.events import Event
from core.event_log import EventLog


def test_event_log_append_and_retrieve():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            event = Event(type="user.message", session_id="s1", payload={"text": "hi"})
            event_id = log.append(event)
            assert event_id == 1

            events = log.get_session_events("s1")
            assert len(events) == 1
            assert events[0].type == "user.message"
            assert events[0].payload == {"text": "hi"}


def test_event_log_replay():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"a": 1}))
            log.append(Event(type="tool.call", session_id="s1", payload={"b": 2}))
            log.append(Event(type="user.message", session_id="s2", payload={"c": 3}))

            events = log.replay("s1")
            assert [e.type for e in events] == ["user.message", "tool.call"]


def test_event_log_schema_created_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log1:
            log1.append(Event(type="x", session_id="s1", payload={}))
        with EventLog(db) as log2:
            log2.append(Event(type="y", session_id="s1", payload={}))
            events = log2.get_session_events("s1")
            assert len(events) == 2


def test_event_log_get_task_events():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="task.start", session_id="s1", task_id="t1", payload={}))
            log.append(Event(type="user.message", session_id="s1", task_id="t1", payload={}))
            log.append(Event(type="task.start", session_id="s1", task_id="t2", payload={}))

            t1_events = log.get_task_events("t1")
            assert len(t1_events) == 2
            assert all(e.task_id == "t1" for e in t1_events)
