from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.plugin import Plugin


class DecisionLogger(Plugin):
    """Zero-token decision logger for AgentLoop routing and tool selection.

    Logs every decision to JSONL files organized by date:
    logs/decisions/decisions_YYYYMMDD.jsonl

    Each log entry contains:
    - timestamp, session_id, turn, decision_type, input, output,
      confidence, duration_ms, alternatives_considered
    """

    name = "decision_logger"
    dependencies = ()

    def __init__(self, log_dir: str | Path = "logs/decisions") -> None:
        super().__init__()
        self._log_dir = Path(log_dir)
        self._session_id: str | None = None
        self._turn: int = 0
        self._enabled: bool = True

    def start(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        if self.context is not None:
            session_id = self._get_session_id()
            self._session_id = session_id

    def stop(self) -> None:
        self._session_id = None
        self._turn = 0

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id

    def increment_turn(self) -> int:
        self._turn += 1
        return self._turn

    def log_decision(
        self,
        decision_type: str,
        input_data: Any,
        output_data: Any,
        confidence: float = 1.0,
        duration_ms: float = 0.0,
        alternatives_considered: list[Any] | None = None,
    ) -> None:
        """Log a decision to the daily JSONL file.

        Args:
            decision_type: Category of decision (e.g., 'tool_selection', 'routing').
            input_data: Input that led to the decision.
            output_data: Output/result of the decision.
            confidence: Confidence score 0.0-1.0.
            duration_ms: Time taken to make the decision in milliseconds.
            alternatives_considered: List of alternative options that were considered.
        """
        if not self._enabled or self.context is None:
            return

        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": self._session_id or "unknown",
            "turn": self._turn,
            "decision_type": decision_type,
            "input": input_data,
            "output": output_data,
            "confidence": confidence,
            "duration_ms": duration_ms,
            "alternatives_considered": alternatives_considered or [],
        }

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_file = self._log_dir / f"decisions_{date_str}.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def _get_session_id(self) -> str:
        event_logger = self.context.plugins.get("event_logger") if self.context else None
        if event_logger is not None and hasattr(event_logger, "continuity"):
            return getattr(event_logger.continuity, "session_id", "unknown")
        return "unknown"

    def health_check(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "plugin": self.name,
            "log_dir": str(self._log_dir),
            "session_id": self._session_id,
            "turn": self._turn,
        }
