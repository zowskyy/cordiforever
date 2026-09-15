from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .event_log import EventLog


class PersonaMemory:
    def __init__(self, event_log: EventLog) -> None:
        self._el = event_log
        self._floor = 0.1
        self._ceil = 0.95
        self._boost = 0.1
        self._penalty = 0.5
        self._ev_boost = 0.05

    def update(self, session_id: str, attribute: str, evidence: str, confidence: float = 1.0, source_event_id: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        row = self._el._conn.execute("SELECT id, confidence FROM persona_memory WHERE session_id = ? AND attribute = ?", (session_id, attribute)).fetchone()
        if row is None:
            self._el._conn.execute("INSERT INTO persona_memory (session_id, attribute, value, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (session_id, attribute, evidence, confidence, now, now))
        else:
            self._el._conn.execute("UPDATE persona_memory SET value = ?, confidence = ?, updated_at = ? WHERE id = ?", (evidence, self._evolve(row[1], confidence), now, row[0]))
        self._el._conn.commit()

    def add_hypothesis(self, session_id: str, attribute: str, hypothesis: str, confidence: float = 0.5, source_event_id: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._el._conn.execute("INSERT INTO persona_hypotheses (session_id, attribute, hypothesis, evidence_count, confidence, source_event_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (session_id, attribute, hypothesis, 1, confidence, source_event_id, now, now))
        self._el._conn.commit()

    def reinforce_hypothesis(self, session_id: str, attribute: str, hypothesis: str, evidence_confidence: float = 1.0) -> None:
        row = self._el._conn.execute("SELECT id, evidence_count, confidence FROM persona_hypotheses WHERE session_id = ? AND attribute = ? AND hypothesis = ?", (session_id, attribute, hypothesis)).fetchone()
        if row:
            now = datetime.now(timezone.utc).isoformat()
            self._el._conn.execute("UPDATE persona_hypotheses SET evidence_count = ?, confidence = ?, updated_at = ? WHERE id = ?", (row[1] + 1, min(self._ceil, row[2] + self._ev_boost), now, row[0]))
            self._el._conn.commit()

    def get_hypotheses(self, session_id: str, attribute: str | None = None, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        q = "SELECT id, attribute, hypothesis, evidence_count, confidence, source_event_id, created_at, updated_at FROM persona_hypotheses WHERE session_id = ?" + (" AND attribute = ?" if attribute else "") + " AND confidence >= ? ORDER BY confidence DESC, evidence_count DESC, updated_at DESC"
        p = (session_id, attribute, min_confidence) if attribute else (session_id, min_confidence)
        return [dict(zip(["id", "attribute", "hypothesis", "evidence_count", "confidence", "source_event_id", "created_at", "updated_at"], r)) for r in self._el._conn.execute(q, p).fetchall()]

    def get_best_hypothesis(self, session_id: str, attribute: str, min_confidence: float = 0.3) -> dict[str, Any] | None:
        hyps = self.get_hypotheses(session_id, attribute, min_confidence)
        return hyps[0] if hyps else None

    def get(self, session_id: str, attribute: str | None = None, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        q = "SELECT attribute, value, confidence, created_at, updated_at FROM persona_memory WHERE session_id = ?" + (" AND attribute = ?" if attribute else "") + " AND confidence >= ? ORDER BY confidence DESC, updated_at DESC"
        p = (session_id, attribute, min_confidence) if attribute else (session_id, min_confidence)
        return [dict(zip(["attribute", "value", "confidence", "created_at", "updated_at"], r)) for r in self._el._conn.execute(q, p).fetchall()]

    def get_profile_summary(self, session_id: str) -> str:
        entries = self.get(session_id, min_confidence=0.3)
        return "; ".join(f"{e['attribute']}: {e['value']} ({e['confidence']:.0%})" for e in entries) if entries else "No persona data available."

    def _evolve(self, current: float, evidence_confidence: float) -> float:
        if evidence_confidence >= 0.8:
            return min(self._ceil, current + self._boost)
        if evidence_confidence <= 0.2:
            return max(self._floor, current * self._penalty)
        return current
