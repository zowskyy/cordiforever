from __future__ import annotations

import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class RecoveryAction:
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    event_type: str | None = None
    tool: str | None = None


class ErrorRecoveryPlugin(EventDrivenPlugin):
    name = "error_recovery"
    dependencies = ("event_logger", "health_monitoring")

    def __init__(self, max_retries: int = 3) -> None:
        super().__init__()
        self._max_retries = max_retries
        self._retry_counts: dict[str, int] = {}
        self._recovery_log: list[dict[str, Any]] = []
        self._max_log_events = 1000

    def start(self) -> None:
        self._load_recovery_state()
        self._log_event({"event": "started", "timestamp": time.time()})

    def stop(self) -> None:
        self._save_recovery_state()
        self._log_event({"event": "stopped", "timestamp": time.time()})

    def handle_failure(self, failure_type: str, context: dict[str, Any]) -> RecoveryAction:
        tool_name = context.get("tool_name", "unknown")
        arguments = context.get("arguments", {})
        key = self._make_key(tool_name, arguments)
        count = self._retry_counts.get(key, 0)

        if failure_type == "timeout" and count >= self._max_retries:
            return RecoveryAction(
                action="fallback",
                payload={"attempt": count, "alternative": "timeout_fallback"},
                reason="timeout_fallback_after_retries",
                event_type="recovery.fallback",
                tool=tool_name,
            )

        if count < self._max_retries:
            delay = self._get_delay(count)
            self._retry_counts[key] = count + 1
            action = RecoveryAction(
                action="retry",
                payload={"attempt": count + 1, "delay": delay, "max": self._max_retries},
                reason="retry_with_backoff",
                event_type="recovery.retry",
                tool=tool_name,
            )
            self._log_event({
                "event": "retry",
                "tool": tool_name,
                "attempt": count + 1,
                "delay": delay,
                "timestamp": time.time(),
            })
            return action

        action = RecoveryAction(
            action="escalate",
            payload={"failure": failure_type, "context": context, "attempt": count},
            reason="retry_budget_exhausted",
            event_type="recovery.escalate",
            tool=tool_name,
        )
        self._log_event({
            "event": "escalate",
            "tool": tool_name,
            "reason": "retry_budget_exhausted",
            "timestamp": time.time(),
        })
        return action

    def reset(self, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        key = self._make_key(tool_name, arguments or {})
        self._retry_counts.pop(key, None)

    def reset_all(self) -> None:
        self._retry_counts.clear()

    def on_tool_result(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        if payload.get("success") is False:
            failure_type = payload.get("error_type", "unknown")
            context = {
                "tool_name": payload.get("tool_name", "unknown"),
                "arguments": payload.get("arguments", {}),
                "result": payload.get("result", ""),
            }
            action = self.handle_failure(failure_type, context)
            if self.context is not None:
                self.context.events.emit("recovery.action", {
                    "action": action.action,
                    "reason": action.reason,
                    "tool": action.tool,
                    "payload": action.payload,
                })

    def on_turn_end(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        if payload.get("final_result") == "" and payload.get("error") == "max_rounds_exceeded":
            self.reset_all()

    def _make_key(self, tool_name: str, arguments: dict[str, Any]) -> str:
        arg_hash = hashlib.md5(str(sorted(arguments.items())).encode()).hexdigest()[:8]
        return f"{tool_name}_{arg_hash}"

    def _get_delay(self, attempt: int) -> float:
        return min(2 ** attempt, 60) + random.uniform(0, 0.5)

    def _load_recovery_state(self) -> None:
        self._retry_counts.clear()

    def _save_recovery_state(self) -> None:
        if self.context is not None:
            self.context.events.emit("recovery.state", {
                "retry_counts": self._retry_counts,
                "timestamp": time.time(),
            })

    def _log_event(self, event: dict[str, Any]) -> None:
        self._recovery_log.append(event)
        if len(self._recovery_log) > self._max_log_events:
            self._recovery_log.pop(0)
