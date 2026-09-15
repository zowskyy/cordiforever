from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.context import Context
from core.events import Event
from core.event_log import EventLog
from core.registry import PluginRegistry
from core.reality import RealityProjector
from plugins.core.event_logger import EventLogger


def test_current_reality_from_dict_roundtrip():
    from core.reality import CurrentReality
    r = CurrentReality(messages=[{"role": "user", "content": "hi"}], files_read={"a.txt"})
    d = r.to_dict()
    r2 = CurrentReality.from_dict(d)
    assert r2.messages == [{"role": "user", "content": "hi"}]
    assert "a.txt" in r2.files_read


def test_reality_projector_builds_from_events():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"content": "hi"}))
            log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read", "arguments": {"path": "a.txt"}, "success": True}))
            proj = RealityProjector(log)
            reality = proj.get_reality("s1")
            assert reality.summary()["message_count"] == 2
            assert "a.txt" in reality.summary()["files_read"]


def test_reality_projector_uses_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            for i in range(60):
                log.append(Event(type="user.message", session_id="s1", payload={"content": f"msg {i}"}))
            proj = RealityProjector(log, snapshot_threshold=50)
            reality = proj.get_reality("s1")
            assert reality.summary()["message_count"] == 60
            assert log.load_snapshot("s1") is not None


def test_reality_summary_counts():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"content": "hi"}))
            log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "arguments": {"path": "a.txt"}, "success": True}))
            log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read", "arguments": {"path": "b.txt"}, "success": False, "error": "not found"}))
            proj = RealityProjector(log)
            s = proj.get_reality("s1").summary()
            assert s["message_count"] == 3
            assert s["error_count"] == 1
