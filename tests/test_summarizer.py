from __future__ import annotations

import tempfile
from pathlib import Path

from core.events import Event
from core.event_log import EventLog
from core.summarizer import Summarizer


def test_heuristic_summary_without_model():
    summarizer = Summarizer(model=None)
    events = [
        Event(type="user.message", session_id="s1", payload={"content": "Fix bug"}),
        Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read", "success": True}),
    ]
    summary = summarizer.summarize_events(events, max_length=200)
    assert "User: Fix bug" in summary
    assert "file_read" in summary


def test_heuristic_summary_empty_events():
    summarizer = Summarizer(model=None)
    assert summarizer.summarize_events([]) == ""


def test_format_events_for_summary():
    summarizer = Summarizer(model=None)
    events = [
        Event(type="user.message", session_id="s1", payload={"content": "hello"}, timestamp="2026-01-01T00:00:00Z"),
        Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "success": True}, timestamp="2026-01-01T00:00:01Z"),
    ]
    text = summarizer._format_events_for_summary(events)
    assert "User: hello" in text
    assert "file_write" in text
