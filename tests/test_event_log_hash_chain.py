from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.events import Event
from core.event_log import EventLog


def test_event_log_hash_chain_integrity():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test_hash.db"
        with EventLog(db) as log:
            e1 = Event(type="user.message", session_id="s1", payload={"text": "hello"})
            e2 = Event(type="tool.call", session_id="s1", payload={"tool": "read"})
            id1 = log.append(e1)
            id2 = log.append(e2)

            events = log.get_session_events("s1")
            assert len(events) == 2
            assert events[0].entry_hash is not None
            assert events[1].entry_hash is not None
            assert events[1].prev_hash == events[0].entry_hash
            assert events[0].prev_hash is None  # first event has no prev


def test_event_log_verify_chain_valid():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test_verify.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"a": 1}))
            log.append(Event(type="tool.call", session_id="s1", payload={"b": 2}))

            result = log.verify_chain("s1")
            assert result["valid"] is True
            assert result["broken_links"] == 0
            assert result["event_count"] == 2


def test_event_log_verify_chain_detects_tampering():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test_tamper.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"a": 1}))
            log.append(Event(type="tool.call", session_id="s1", payload={"b": 2}))

        # Tamper with the DB directly
        import sqlite3
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE events SET payload = '{\"a\": 999}' WHERE id = 1")
        conn.commit()
        conn.close()

        with EventLog(db) as log:
            result = log.verify_chain("s1")
            assert result["valid"] is False
            assert result["broken_links"] > 0


def test_event_log_hash_chain_multiple_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test_multi.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"a": 1}))
            log.append(Event(type="user.message", session_id="s2", payload={"b": 2}))
            log.append(Event(type="tool.call", session_id="s1", payload={"c": 3}))

            r1 = log.verify_chain("s1")
            r2 = log.verify_chain("s2")
            assert r1["valid"] is True
            assert r1["event_count"] == 2
            assert r2["valid"] is True
            assert r2["event_count"] == 1
