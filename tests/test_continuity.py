from __future__ import annotations

import tempfile
from pathlib import Path

from core.continuity import Continuity
from core.event_log import EventLog


def test_continuity_session_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            c = Continuity(log)
            assert c.session_id is not None
            events = log.get_session_events(c.session_id)
            assert any(e.type == "session.start" for e in events)

            c.end_session()
            events = log.get_session_events(c.session_id)
            assert any(e.type == "session.end" for e in events)


def test_continuity_task_lifecycle():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            c = Continuity(log)
            task_id = c.start_task("fix bug")
            assert c.task_id == task_id

            events = log.get_task_events(task_id)
            assert any(e.type == "task.start" for e in events)

            c.end_task()
            assert c.task_id is None
            events = log.get_task_events(task_id)
            assert any(e.type == "task.end" for e in events)


def test_continuity_replay():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            c = Continuity(log)
            c.start_task("demo")
            c.emit("user.message", {"text": "hello"})

            events = c.replay()
            types = [e.type for e in events]
            assert "session.start" in types
            assert "task.start" in types
            assert "user.message" in types
