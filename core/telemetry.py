from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .events import Event
from .event_log import EventLog


class AgentTelemetry:
    """Privacy-safe structured tracing."""

    def __init__(self, event_log: EventLog) -> None:
        self._event_log = event_log
        self._redaction_rules = [
            r"(api[_-]?key|token|password|secret|private[_-]?key)\s*[:=]\s*\S+",
            r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----.*?-----END\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
            r"(sk-[A-Za-z0-9]{8,})",
            r"(ghp_[A-Za-z0-9]{36})",
            r"(AKIA[A-Z0-9]{16})",
            r"(xox[bpar]-[A-Za-z0-9-]+)",
            r"([0-9a-f]{32,})",
            r"(eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+)",
        ]

    def trace(self, layer: str, event: str, data: dict[str, Any]) -> None:
        redacted = self._redact(data)
        self._event_log.append(
            Event(
                type=f"trace.{layer}",
                session_id=data.get("session_id", ""),
                payload={
                    "event": event,
                    "data": redacted,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        )

    def _redact(self, data: dict[str, Any]) -> dict[str, Any]:
        text = json.dumps(data, ensure_ascii=False, default=str)
        for pattern in self._redaction_rules:
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE | re.DOTALL)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "redaction_failed"}
