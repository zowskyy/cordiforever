from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .events import Event
from .event_log import EventLog


class SemanticMemory:
    def __init__(self, event_log: EventLog) -> None:
        self._el = event_log
        self._df: dict[str, int] = {}
        self._n = 0

    @staticmethod
    def _tok(text: str) -> list[str]:
        return [t for t in text.lower().split() if t.isalnum()]

    def _tfidf(self, text: str) -> dict[str, float]:
        tokens = self._tok(text)
        if not tokens:
            return {}
        tf = Counter(tokens)
        total = len(tokens)
        return {t: (c / total) * (math.log((self._n + 1) / (self._df.get(t, 0) + 1)) + 1) for t, c in tf.items()}

    @staticmethod
    def _cos(a: dict[str, float], b: dict[str, float]) -> float:
        common = a.keys() & b.keys()
        if not common:
            return 0.0
        dot = sum(a[k] * b[k] for k in common)
        mag = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
        return dot / mag if mag else 0.0

    def index_events(self, session_id: str) -> None:
        events = self._el.get_session_events(session_id)
        self._n = len(events)
        self._df = {}
        for e in events:
            for t in set(self._tok(self._text(e))):
                self._df[t] = self._df.get(t, 0) + 1
        for e in events:
            vec = self._tfidf(self._text(e))
            self._el._conn.execute(
                "INSERT OR REPLACE INTO semantic_index (event_id, session_id, tfidf, text, created_at) VALUES (?, ?, ?, ?, ?)",
                (e.id, session_id, json.dumps(vec, ensure_ascii=False), self._text(e), e.timestamp),
            )
        self._el._conn.commit()

    def add_note(self, session_id: str, event_id: int, note_type: str, content: str, confidence: float = 1.0) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._el._conn.execute(
            "INSERT INTO semantic_notes (session_id, event_id, note_type, content, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, event_id, note_type, content, confidence, now, now),
        )
        self._el._conn.commit()

    def retrieve_notes(self, session_id: str, note_type: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        q = "SELECT id, event_id, note_type, content, confidence, created_at FROM semantic_notes WHERE session_id = ?" + (" AND note_type = ?" if note_type else "") + " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        p = (session_id, note_type, limit) if note_type else (session_id, limit)
        return [dict(zip(["id", "event_id", "note_type", "content", "confidence", "created_at"], r)) for r in self._el._conn.execute(q, p).fetchall()]

    def retrieve_episodes(self, session_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        qv = self._tfidf(query)
        if not qv:
            return []
        rows = self._el._conn.execute("SELECT event_id, tfidf, text FROM semantic_index WHERE session_id = ?", (session_id,)).fetchall()
        scored = [{"event_id": r[0], "score": self._cos(qv, json.loads(r[1])), "text": r[2]} for r in rows]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def hybrid_retrieve(self, session_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        notes = self.retrieve_notes(session_id, limit=top_k)
        episodes = self.retrieve_episodes(session_id, query, top_k)
        results = [{"type": "note", "score": n["confidence"], "data": n} for n in notes] + [{"type": "episode", "score": e["score"], "data": e} for e in episodes]
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def reconsolidate(self, session_id: str, new_notes: list[dict[str, Any]]) -> None:
        for note in new_notes:
            row = self._el._conn.execute(
                "SELECT id, confidence FROM semantic_notes WHERE session_id = ? AND note_type = ? AND content = ?",
                (session_id, note["note_type"], note["content"]),
            ).fetchone()
            if not row:
                self.add_note(session_id, note.get("event_id", 0), note["note_type"], note["content"], note.get("confidence", 1.0))
            else:
                conf = row[1]
                new_conf = max(0.1, conf * 0.5) if note.get("contradicts") else min(1.0, conf + 0.1)
                now = datetime.now(timezone.utc).isoformat()
                self._el._conn.execute("UPDATE semantic_notes SET confidence = ?, updated_at = ? WHERE id = ?", (new_conf, now, row[0]))
        self._el._conn.commit()

    def _text(self, event: Event) -> str:
        p = event.payload or {}
        return " ".join(filter(None, [event.type, str(p.get("content", "")), str(p.get("tool_name", "")), str(p.get("result", "")), str(p.get("error", ""))]))
