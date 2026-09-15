from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .events import Event
from .event_log import EventLog


class EpisodicMemory:
    def __init__(self, event_log: EventLog, model: Any = None) -> None:
        self._event_log = event_log
        self._model = model

    def remember(self, event: Event, summary: str, tags: list[str] | None = None) -> None:
        self._event_log._conn.execute(
            "INSERT OR IGNORE INTO episodic_memory (session_id, event_id, summary, tags, importance, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event.session_id, event.id, summary, json.dumps(tags or []), 1.0, datetime.now(timezone.utc).isoformat()),
        )
        self._event_log._conn.commit()

    def recall(self, session_id: str, query: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        q = "SELECT summary, tags, importance, created_at, id FROM episodic_memory WHERE session_id = ?" + (" AND summary LIKE ?" if query else "") + " ORDER BY importance DESC, created_at DESC, id DESC LIMIT ?"
        p = (session_id, f"%{query}%", limit) if query else (session_id, limit)
        rows = self._event_log._conn.execute(q, p).fetchall()
        return [{"summary": r[0], "tags": json.loads(r[1]) if r[1] else [], "importance": r[2], "created_at": r[3]} for r in rows]

    def decay(self, session_id: str, keep_limit: int = 100) -> None:
        rows = self._event_log._conn.execute(
            "SELECT id FROM episodic_memory WHERE session_id = ? ORDER BY importance DESC, created_at DESC",
            (session_id,),
        ).fetchall()
        if len(rows) <= keep_limit:
            return
        ids = [r[0] for r in rows[keep_limit:]]
        self._event_log._conn.execute(f"DELETE FROM episodic_memory WHERE id IN ({','.join('?' * len(ids))})", ids)
        self._event_log._conn.commit()
