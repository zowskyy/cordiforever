from __future__ import annotations

import tempfile
from pathlib import Path

from core.closed_loop_retrieval import ClosedLoopRetrieval
from core.events import Event
from core.event_log import EventLog
from core.semantic_memory import SemanticMemory


def test_closed_loop_note_first_succeeds_with_good_notes():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            e = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "result": "ok"})
            e.id = log.append(e)
            semantic = SemanticMemory(log)
            semantic.add_note("s1", e.id, "fact", "User wrote a file", confidence=0.9)
            semantic.index_events("s1")

            retriever = ClosedLoopRetrieval(log, semantic)
            result = retriever.retrieve("s1", "what did user do", "note_first")
            assert result.mode == "note_first"
            assert len(result.notes) == 1
            assert result.evidence_gap is False


def test_closed_loop_escalates_when_notes_insufficient():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            semantic = SemanticMemory(log)
            retriever = ClosedLoopRetrieval(log, semantic)
            result = retriever.retrieve("s1", "what happened", "note_first")
            assert result.mode == "hybrid"
            assert result.evidence_gap is True
            assert result.gap_reason == "insufficient_notes"


def test_closed_loop_episode_first_escalates_when_episodes_insufficient():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            e = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "result": "ok"})
            e.id = log.append(e)
            semantic = SemanticMemory(log)
            semantic.add_note("s1", e.id, "fact", "Wrote file", confidence=0.9)
            semantic.index_events("s1")

            retriever = ClosedLoopRetrieval(log, semantic)
            result = retriever.retrieve("s1", "unknown zzz topic", "episode_first")
            assert result.mode == "hybrid"
            assert result.evidence_gap is True
            assert result.gap_reason == "insufficient_episodes"


def test_closed_loop_hybrid_returns_both():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            e = Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "result": "ok"})
            e.id = log.append(e)
            semantic = SemanticMemory(log)
            semantic.add_note("s1", e.id, "fact", "Wrote file", confidence=0.9)
            semantic.index_events("s1")

            retriever = ClosedLoopRetrieval(log, semantic)
            result = retriever.retrieve("s1", "write", "hybrid")
            assert result.mode == "hybrid"
            assert result.evidence_gap is False
            assert len(result.notes) >= 1
