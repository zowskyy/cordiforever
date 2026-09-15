from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import Event


class EventLog:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), detect_types=sqlite3.PARSE_DECLTYPES)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def append(self, event: Event) -> int:
        prev_hash = self._last_entry_hash(event.session_id)
        entry_data = {
            "timestamp": event.timestamp,
            "type": event.type,
            "session_id": event.session_id,
            "task_id": event.task_id,
            "parent_event_id": event.parent_event_id,
            "operation_id": event.operation_id,
            "payload": event.payload,
            "prev_hash": prev_hash,
        }
        entry_hash = hashlib.sha256(
            json.dumps(entry_data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        cur = self._conn.execute(
            "INSERT INTO events (timestamp, type, session_id, task_id, parent_event_id, operation_id, payload, prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.timestamp,
                event.type,
                event.session_id,
                event.task_id,
                event.parent_event_id,
                event.operation_id,
                json.dumps(event.payload, ensure_ascii=False),
                prev_hash,
                entry_hash,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_session_events(self, session_id: str) -> list[Event]:
        return self._rows("SELECT * FROM events WHERE session_id = ? ORDER BY id ASC", (session_id,))

    def get_task_events(self, task_id: str) -> list[Event]:
        return self._rows("SELECT * FROM events WHERE task_id = ? ORDER BY id ASC", (task_id,))

    def replay(self, session_id: str) -> list[Event]:
        return self.get_session_events(session_id)

    def get_step_traces(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT step_id, tool_name, input, output, duration_ms, error_type, token_cost, context_size_before, context_size_after, dependency_ids, parallelizable, governance_check_passed, timestamp FROM step_trace WHERE session_id = ? ORDER BY timestamp ASC",
            (session_id,),
        ).fetchall()
        return [
            {
                "step_id": r[0],
                "tool_name": r[1],
                "input": json.loads(r[2]) if r[2] else {},
                "output": r[3],
                "duration_ms": r[4],
                "error_type": r[5],
                "token_cost": r[6],
                "context_size_before": r[7],
                "context_size_after": r[8],
                "dependency_ids": json.loads(r[9]) if r[9] else [],
                "parallelizable": bool(r[10]),
                "governance_check_passed": bool(r[11]),
                "timestamp": r[12],
            }
            for r in rows
        ]

    def append_step_trace(self, step: TraceStep) -> None:
        self._conn.execute(
            "INSERT INTO step_trace (step_id, session_id, tool_name, input, output, duration_ms, error_type, token_cost, context_size_before, context_size_after, dependency_ids, parallelizable, governance_check_passed, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                step.step_id,
                step.session_id,
                step.tool_name,
                json.dumps(step.input, ensure_ascii=False),
                step.output,
                step.duration_ms,
                step.error_type,
                step.token_cost,
                step.context_size_before,
                step.context_size_after,
                json.dumps(step.dependency_ids, ensure_ascii=False),
                int(step.parallelizable),
                int(step.governance_check_passed),
                step.timestamp,
            ),
        )
        self._conn.commit()

    def get_last_event(self, session_id: str) -> Event | None:
        rows = self._conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,)).fetchall()
        return Event.from_row(tuple(rows[0])) if rows else None

    def get_events_after(self, session_id: str, version: int) -> list[Event]:
        return self._rows("SELECT * FROM events WHERE session_id = ? AND id > ? ORDER BY id ASC", (session_id, version))

    def _last_entry_hash(self, session_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT entry_hash FROM events WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return row[0] if row else None

    def verify_chain(self, session_id: str) -> dict[str, Any]:
        events = self.get_session_events(session_id)
        expected_prev = None
        broken: list[dict[str, Any]] = []
        for event in events:
            if event.prev_hash != expected_prev:
                broken.append({
                    "event_id": event.id,
                    "expected_prev": expected_prev,
                    "actual_prev": event.prev_hash,
                })
            entry_data = {
                "timestamp": event.timestamp,
                "type": event.type,
                "session_id": event.session_id,
                "task_id": event.task_id,
                "parent_event_id": event.parent_event_id,
                "operation_id": event.operation_id,
                "payload": event.payload,
                "prev_hash": event.prev_hash,
            }
            expected_hash = hashlib.sha256(
                json.dumps(entry_data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
            ).hexdigest()
            if event.entry_hash != expected_hash:
                broken.append({
                    "event_id": event.id,
                    "expected_hash": expected_hash,
                    "actual_hash": event.entry_hash,
                })
            expected_prev = event.entry_hash
        return {
            "session_id": session_id,
            "event_count": len(events),
            "broken_links": len(broken),
            "details": broken,
            "valid": len(broken) == 0,
        }

    def mark_session_outcome(self, session_id: str, outcome: str, metadata: dict[str, Any] | None = None) -> int:
        """Record the outcome of a session for training data collection.

        Args:
            session_id: The session identifier.
            outcome: "success", "partial", or "failure".
            metadata: Additional data (files_created, tools_used, model_turns, app_type, etc.).

        Returns:
            Row ID of the inserted outcome event.
        """
        payload = {"outcome": outcome, "timestamp": datetime.now(timezone.utc).isoformat()}
        if metadata:
            payload.update(metadata)
        cur = self._conn.execute(
            "INSERT INTO events (timestamp, type, session_id, task_id, parent_event_id, operation_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                payload["timestamp"],
                "session.outcome",
                session_id,
                None,
                None,
                None,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def query(self, query: str, params: tuple = ()) -> list[tuple]:
        """Execute an arbitrary read query (for data exporter use).

        Args:
            query: SQL query string.
            params: Query parameters.

        Returns:
            List of row tuples.
        """
        return self._conn.execute(query, params).fetchall()

    def save_snapshot(self, stream_id: str, version: int, state: dict, compress: bool = True) -> None:
        raw = json.dumps(state, ensure_ascii=False, default=str)
        if compress:
            import base64
            raw = base64.b64encode(zlib.compress(raw.encode())).decode("ascii")
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots (stream_id, version, state, compressed, created_at) VALUES (?, ?, ?, ?, ?)",
            (stream_id, version, raw, int(compress), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def load_snapshot(self, stream_id: str) -> tuple[int, dict] | None:
        row = self._conn.execute("SELECT version, state, compressed FROM snapshots WHERE stream_id = ?", (stream_id,)).fetchone()
        if not row:
            return None
        version, state, compressed = row
        if compressed:
            import base64
            try:
                state = zlib.decompress(base64.b64decode(state.encode("ascii"))).decode()
            except Exception:
                # backward compat: old latin-1 path
                try:
                    state = zlib.decompress(state.encode("latin-1")).decode()
                except Exception:
                    return None
        return version, json.loads(state)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> EventLog:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _rows(self, query, params):
        return [Event.from_row(tuple(r)) for r in self._conn.execute(query, params).fetchall()]


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    type TEXT NOT NULL, session_id TEXT NOT NULL, task_id TEXT,
    parent_event_id INTEGER, operation_id TEXT, payload TEXT NOT NULL,
    prev_hash TEXT, entry_hash TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    stream_id TEXT PRIMARY KEY, version INTEGER NOT NULL, state TEXT NOT NULL,
    compressed INTEGER DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    event_id INTEGER NOT NULL UNIQUE, summary TEXT NOT NULL, tags TEXT,
    importance REAL DEFAULT 1.0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    event_id INTEGER NOT NULL, note_type TEXT NOT NULL, content TEXT NOT NULL,
    confidence REAL DEFAULT 1.0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id)
);
CREATE TABLE IF NOT EXISTS persona_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    attribute TEXT NOT NULL, value TEXT NOT NULL, confidence REAL NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS persona_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    attribute TEXT NOT NULL, hypothesis TEXT NOT NULL, evidence_count INTEGER DEFAULT 1,
    confidence REAL NOT NULL, source_event_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY (source_event_id) REFERENCES events(id)
);
CREATE TABLE IF NOT EXISTS semantic_index (
    event_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
    tfidf TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id)
);
CREATE TABLE IF NOT EXISTS step_trace (
    step_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    error_type TEXT,
    token_cost INTEGER DEFAULT 0,
    context_size_before INTEGER DEFAULT 0,
    context_size_after INTEGER DEFAULT 0,
    dependency_ids TEXT NOT NULL,
    parallelizable INTEGER DEFAULT 0,
    governance_check_passed INTEGER DEFAULT 1,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_memory_session ON episodic_memory(session_id);
CREATE INDEX IF NOT EXISTS idx_semantic_session ON semantic_index(session_id);
CREATE INDEX IF NOT EXISTS idx_notes_session ON semantic_notes(session_id);
CREATE INDEX IF NOT EXISTS idx_notes_type ON semantic_notes(note_type);
CREATE INDEX IF NOT EXISTS idx_persona_session ON persona_memory(session_id);
"""
