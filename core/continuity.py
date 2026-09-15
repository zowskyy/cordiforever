from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from .events import Event

if TYPE_CHECKING:
    from .event_log import EventLog


class Continuity:
    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log
        self._session_id = self._new_id("session")
        self._task_id: str | None = None
        self._emit("session.start", {"session_id": self._session_id})

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:8]}"

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        event = Event(
            type=event_type,
            session_id=self._session_id,
            task_id=self._task_id,
            payload=payload,
        )
        self._event_log.append(event)

    def start_task(self, description: str = "") -> str:
        if self._task_id is None:
            self._task_id = self._new_id("task")
        self._emit(
            "task.start",
            {"task_id": self._task_id, "description": description},
        )
        return self._task_id

    def end_task(self) -> None:
        if self._task_id is not None:
            self._emit("task.end", {"task_id": self._task_id})
            self._task_id = None

    def end_session(self) -> None:
        self._emit("session.end", {"session_id": self._session_id})

    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        self._emit(event_type, payload)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def task_id(self) -> str | None:
        return self._task_id

    def replay(self) -> list[Event]:
        return self._event_log.replay(self._session_id)
