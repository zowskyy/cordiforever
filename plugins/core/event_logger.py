from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.continuity import Continuity
from core.events import Event, STEP_TRACE, TraceStep
from core.event_log import EventLog
from core.plugin import Plugin


class EventLogger(Plugin):
    name = "event_logger"
    dependencies = ()

    def __init__(self, db_path: str | Path = "continuity/continuity.db") -> None:
        super().__init__()
        self._db_path = db_path
        self._step_counter = 0
        self._last_context_size = 0

    def register(self, context: Any) -> None:
        super().register(context)
        self._event_log = EventLog(self._db_path)
        self._continuity = Continuity(self._event_log)
        # Access via ctx.plugins["event_logger"].event_log / .continuity per invariant 2.5

    def start(self) -> None:
        if self.context is not None:
            self.context.events.on("user.message", self._on_user_message)
            self.context.events.on("system.message", self._on_system_message)
            self.context.events.on("assistant.message", self._on_assistant_message)
            self.context.events.on("tool.invoked", self._on_tool_invoked)
            self.context.events.on("tool.result", self._on_tool_result)
            self.context.events.on("context.pruned", self._on_context_pruned)
            self.context.events.on("memory.augmented", self._on_memory_augmented)
            self.context.events.on("replan", self._on_replan)
            self.context.events.on("turn.start", self._on_turn_start)
            self.context.events.on("turn.round", self._on_turn_round)
            self.context.events.on("turn.end", self._on_turn_end)
            self.context.events.on("ci.status.updated", self._on_ci_status)
            self.context.events.on("math.solved", self._on_math_solved)
            self.context.events.on("lifecycle.consolidated", self._on_lifecycle_consolidated)
            self.context.events.on("persona.updated", self._on_persona_updated)
            self.context.events.on("protected_file.violation", self._on_protected_file_violation)

    def stop(self) -> None:
        self._continuity.end_session()
        self._event_log.close()

    def _on_user_message(self, event) -> None:
        self.emit("user.message", event.payload or {})

    def _on_system_message(self, event) -> None:
        self.emit("system.message", event.payload or {})

    def _on_assistant_message(self, event) -> None:
        self.emit("assistant.message", event.payload or {})

    def _on_tool_invoked(self, event) -> None:
        self.emit("tool.invoked", event.payload or {})

    def _on_tool_result(self, event) -> None:
        self.emit("tool.result", event.payload or {})

    def _on_context_pruned(self, event) -> None:
        self.emit("context.pruned", event.payload or {})

    def _on_memory_augmented(self, event) -> None:
        self.emit("memory.augmented", event.payload or {})

    def _on_replan(self, event) -> None:
        self.emit("replan", event.payload or {})

    def _on_turn_start(self, event) -> None:
        self.emit("turn.start", event.payload or {})

    def _on_turn_round(self, event) -> None:
        self.emit("turn.round", event.payload or {})

    def _on_turn_end(self, event) -> None:
        self.emit("turn.end", event.payload or {})

    def _on_ci_status(self, event) -> None:
        self.emit("ci.status.updated", event.payload or {})

    def _on_math_solved(self, event) -> None:
        self.emit("math.solved", event.payload or {})

    def _on_lifecycle_consolidated(self, event) -> None:
        self.emit("lifecycle.consolidated", event.payload or {})

    def _on_persona_updated(self, event) -> None:
        self.emit("persona.updated", event.payload or {})

    def _on_protected_file_violation(self, event) -> None:
        self.emit("protected_file.violation", event.payload or {})

    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        event = Event(
            type=event_type,
            session_id=self._continuity.session_id,
            task_id=self._continuity.task_id,
            payload=payload,
        )
        self._event_log.append(event)

    def mark_session_outcome(self, outcome: str, metadata: dict[str, Any] | None = None) -> int:
        """Record the outcome of a session for training data collection.

        Args:
            outcome: "success", "partial", or "failure".
            metadata: Additional data (files_created, tools_used, model_turns, app_type, etc.).

        Returns:
            Row ID of the inserted outcome event.
        """
        return self._event_log.mark_session_outcome(self._continuity.session_id, outcome, metadata)

    def get_session_outcome(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve the outcome event for a session, if one exists."""
        rows = self._event_log.query(
            "SELECT payload FROM events WHERE session_id = ? AND type = 'session.outcome' ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        if not rows:
            return None
        return json.loads(rows[0][0])

    def start_step(self, tool_name: str, arguments: dict[str, Any]) -> TraceStep:
        self._step_counter += 1
        step_id = f"step_{self._step_counter}"
        context_size = len(self._continuity.context.messages) if hasattr(self._continuity, 'context') else 0
        return TraceStep(
            step_id=step_id,
            session_id=self._continuity.session_id,
            tool_name=tool_name,
            input=arguments,
            context_size_before=context_size,
            dependency_ids=[],
        )

    def finish_step(self, step: TraceStep, output: str = "", error: str | None = None) -> None:
        step.output = output
        step.error_type = error
        step.duration_ms = 0.0
        step.token_cost = 0
        context_size = len(self._continuity.context.messages) if hasattr(self._continuity, 'context') else 0
        step.context_size_after = context_size
        self._event_log.append_step_trace(step)
        self._last_context_size = context_size

    def last_context_size(self) -> int:
        return self._last_context_size

    @property
    def event_log(self) -> EventLog:
        return self._event_log

    @property
    def continuity(self) -> Continuity:
        return self._continuity
