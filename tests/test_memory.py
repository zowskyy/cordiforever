from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from core.memory import EpisodicMemory
from plugins.core.event_logger import EventLogger


def test_remember_and_recall(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        mem = EpisodicMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write"})
        e.id = ctx.plugins["event_logger"].event_log.append(e)
        mem.remember(e, "Wrote file.txt", tags=["file_write"])
        memories = mem.recall("s1", limit=5)
        assert len(memories) == 1
        assert memories[0]["summary"] == "Wrote file.txt"
        assert "file_write" in memories[0]["tags"]
    finally:
        reg.stop_all()


def test_recall_filtered_by_query(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        mem = EpisodicMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e1 = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write"})
        e2 = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read"})
        e1.id = ctx.plugins["event_logger"].event_log.append(e1)
        e2.id = ctx.plugins["event_logger"].event_log.append(e2)
        mem.remember(e1, "Wrote file.txt", tags=["file_write"])
        mem.remember(e2, "Read file.txt", tags=["file_read"])
        results = mem.recall("s1", query="Wrote")
        assert len(results) == 1
        assert results[0]["summary"] == "Wrote file.txt"
    finally:
        reg.stop_all()


def test_recall_returns_latest_first(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        mem = EpisodicMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e1 = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write"})
        e2 = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read"})
        e1.id = ctx.plugins["event_logger"].event_log.append(e1)
        e2.id = ctx.plugins["event_logger"].event_log.append(e2)
        mem.remember(e1, "First", tags=[])
        mem.remember(e2, "Second", tags=[])
        results = mem.recall("s1", limit=10)
        assert results[0]["summary"] == "Second"
    finally:
        reg.stop_all()


def test_remember_ignores_duplicate_event_id(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        mem = EpisodicMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write"})
        e.id = ctx.plugins["event_logger"].event_log.append(e)
        mem.remember(e, "First")
        mem.remember(e, "Duplicate")
        results = mem.recall("s1", limit=10)
        assert len(results) == 1
        assert results[0]["summary"] == "First"
    finally:
        reg.stop_all()
