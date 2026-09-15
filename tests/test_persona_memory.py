from __future__ import annotations

import tempfile
from pathlib import Path

from core.events import Event
from core.event_log import EventLog
from core.persona_memory import PersonaMemory


def test_persona_update_creates_new_attribute():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.update("s1", "preference", "likes python", confidence=0.8)
            entries = persona.get("s1")
            assert len(entries) == 1
            assert entries[0]["value"] == "likes python"
            assert entries[0]["confidence"] == 0.8


def test_persona_confidence_boosts_on_reinforcement():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.update("s1", "preference", "likes python", confidence=0.5)
            persona.update("s1", "preference", "likes python", confidence=0.9)
            entries = persona.get("s1")
            assert entries[0]["confidence"] > 0.5


def test_persona_confidence_drops_on_contradiction():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.update("s1", "preference", "likes python", confidence=0.9)
            persona.update("s1", "preference", "likes python", confidence=0.1)
            entries = persona.get("s1")
            assert entries[0]["confidence"] < 0.9


def test_persona_get_filtered_by_min_confidence():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.update("s1", "language", "python", confidence=0.9)
            persona.update("s1", "framework", "django", confidence=0.2)
            entries = persona.get("s1", min_confidence=0.5)
            assert len(entries) == 1
            assert entries[0]["attribute"] == "language"


def test_persona_profile_summary():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.update("s1", "language", "python", confidence=0.9)
            persona.update("s1", "style", "concise", confidence=0.8)
            summary = persona.get_profile_summary("s1")
            assert "language" in summary
            assert "style" in summary


def test_persona_add_hypothesis():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.add_hypothesis("s1", "preference", "likes python", confidence=0.6)
            hypotheses = persona.get_hypotheses("s1")
            assert len(hypotheses) == 1
            assert hypotheses[0]["hypothesis"] == "likes python"
            assert hypotheses[0]["evidence_count"] == 1


def test_persona_reinforce_hypothesis_increases_evidence_count():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.add_hypothesis("s1", "preference", "likes python", confidence=0.5)
            persona.reinforce_hypothesis("s1", "preference", "likes python")
            hypotheses = persona.get_hypotheses("s1")
            assert hypotheses[0]["evidence_count"] == 2
            assert hypotheses[0]["confidence"] > 0.5


def test_persona_get_best_hypothesis():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            persona.add_hypothesis("s1", "preference", "likes python", confidence=0.9)
            persona.add_hypothesis("s1", "preference", "likes java", confidence=0.3)
            best = persona.get_best_hypothesis("s1", "preference")
            assert best["hypothesis"] == "likes python"


def test_persona_hypothesis_with_source_event_id():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            persona = PersonaMemory(log)
            event = log.append(Event(type="user.message", session_id="s1", payload={"content": "I like python"}))
            persona.add_hypothesis("s1", "preference", "likes python", source_event_id=event)
            hypotheses = persona.get_hypotheses("s1")
            assert hypotheses[0]["source_event_id"] == event
