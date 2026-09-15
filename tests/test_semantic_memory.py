from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from core.semantic_memory import SemanticMemory
from plugins.core.event_logger import EventLogger


def test_add_and_retrieve_note(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        sem = SemanticMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e = Event(type="tool.result", session_id="s1", payload={"tool_name": "write_file", "arguments": {"path": "f.txt"}})
        e.id = ctx.plugins["event_logger"].event_log.append(e)
        sem.add_note("s1", e.id, "file_write", "Wrote f.txt", 0.9)
        notes = sem.retrieve_notes("s1")
        assert len(notes) == 1
        assert notes[0]["note_type"] == "file_write"
    finally:
        reg.stop_all()


def test_retrieve_notes_filtered_by_type(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        sem = SemanticMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e1 = Event(type="tool.result", session_id="s1", payload={"tool_name": "write_file"})
        e2 = Event(type="tool.result", session_id="s1", payload={"tool_name": "read_file"})
        e1.id = ctx.plugins["event_logger"].event_log.append(e1)
        e2.id = ctx.plugins["event_logger"].event_log.append(e2)
        sem.add_note("s1", e1.id, "file_write", "Wrote file", 0.9)
        sem.add_note("s1", e2.id, "file_read", "Read file", 0.8)
        notes = sem.retrieve_notes("s1", note_type="file_write")
        assert len(notes) == 1
        assert notes[0]["note_type"] == "file_write"
    finally:
        reg.stop_all()


def test_hybrid_retrieve_combines_notes_and_episodes(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        sem = SemanticMemory(ctx.plugins["event_logger"].event_log)
        from core.events import Event
        e = Event(type="user.message", session_id="s1", payload={"content": "hello world"})
        ctx.plugins["event_logger"].event_log.append(e)
        sem.index_events("s1")
        results = sem.hybrid_retrieve("s1", "hello", top_k=5)
        assert len(results) >= 1
        types = {r["type"] for r in results}
        assert "note" in types or "episode" in types
    finally:
        reg.stop_all()


def test_reconsolidate_adds_independent_note(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        sem = SemanticMemory(ctx.plugins["event_logger"].event_log)
        sem.reconsolidate("s1", [{"note_type": "fact", "content": "sky is blue", "event_id": 1}])
        notes = sem.retrieve_notes("s1", note_type="fact")
        assert len(notes) == 1
    finally:
        reg.stop_all()


def test_reconsolidate_boosts_extendable_note(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        sem = SemanticMemory(ctx.plugins["event_logger"].event_log)
        sem.add_note("s1", 1, "fact", "sky is blue", 0.5)
        sem.reconsolidate("s1", [{"note_type": "fact", "content": "sky is blue"}])
        notes = sem.retrieve_notes("s1", note_type="fact")
        assert notes[0]["confidence"] > 0.5
    finally:
        reg.stop_all()


def test_reconsolidate_downgrades_contradictory_note(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.start_all()
    try:
        sem = SemanticMemory(ctx.plugins["event_logger"].event_log)
        sem.add_note("s1", 1, "fact", "sky is blue", 0.9)
        sem.reconsolidate("s1", [{"note_type": "fact", "content": "sky is blue", "contradicts": True}])
        notes = sem.retrieve_notes("s1", note_type="fact")
        assert notes[0]["confidence"] < 0.9
    finally:
        reg.stop_all()
