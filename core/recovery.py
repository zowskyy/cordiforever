from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecoveryAction:
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    event_type: str | None = None
    tool: str | None = None


class RecoveryManager:
    IDEMPOTENT_TOOLS = {"file_read", "file_list", "file_write", "file_search", "code_check", "regex_search", "grep"}

    def __init__(self, event_log: Any) -> None:
        self._event_log = event_log

    def wake(self, session_id: str) -> RecoveryAction:
        last = self._event_log.get_last_event(session_id)
        if last is None:
            return RecoveryAction(action="step")
        if not self._recoverable(last, session_id):
            return RecoveryAction(action="fail", reason="semantic", event_type=last.type)
        handlers = {
            "user.message": lambda: RecoveryAction(action="step"),
            "assistant.message": lambda: RecoveryAction(action="step"),
            "tool.invoked": lambda: self._tool_invoked(last),
            "tool.result": lambda: RecoveryAction(action="step"),
            "gen.start": lambda: RecoveryAction(action="resume_gen", payload={"event_id": last.id}),
            "gen.complete": lambda: RecoveryAction(action="step"),
            "gen.sent": lambda: RecoveryAction(action="done"),
        }
        return handlers.get(last.type, lambda: RecoveryAction(action="fail", reason="unknown", event_type=last.type))()

    def _recoverable(self, event, session_id):
        if event.type == "gen.sent":
            return False
        return not any(e.type == "gen.sent" for e in self._event_log.get_events_after(session_id, event.id))

    def _tool_invoked(self, event):
        p = event.payload or {}
        cid, tn = p.get("call_id"), p.get("tool_name")
        if not cid or not tn:
            return RecoveryAction(action="fail", reason="unknown", event_type=event.type)
        if tn not in self.IDEMPOTENT_TOOLS:
            return RecoveryAction(action="fail", reason="non_idempotent", tool=tn)
        return RecoveryAction(action="retry_tool", payload={"call_id": cid, "tool_name": tn})

    def get_active_sessions(self) -> list[str]:
        return [r[0] for r in self._event_log._conn.execute(
            "SELECT DISTINCT session_id FROM events WHERE session_id IS NOT NULL AND session_id NOT IN (SELECT session_id FROM events WHERE type = ?)",
            ("task.completed",),
        ).fetchall()]
