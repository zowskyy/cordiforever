"""Tool result pruner plugin — compaction and spill for oversized tool results.

This plugin implements the deepseek-harness pattern of threshold/head/tail
compaction plus spill-to-disk for tool results that would otherwise consume
the full context window. It is zero-token: it never calls the model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from core.plugin import Plugin
from core.events import TOOL_RESULT_PRUNED, TOOL_RESULT_SPILLED


class ToolResultPruner(Plugin):
    """Prune or spill oversized tool results before they reach the model.

    Configuration (via Context.config or defaults):
    - ``tool_result_pruner.threshold_chars``: result length threshold in characters.
    - ``tool_result_pruner.head_chars``: characters to keep from the head.
    - ``tool_result_pruner.tail_chars``: characters to keep from the tail.
    - ``tool_result_pruner.spill_dir``: directory for spilled files.
    """

    name = "tool_result_pruner"
    dependencies = ("event_logger",)

    def __init__(self) -> None:
        super().__init__()
        self.__contract__ = {
            "version": "1.0",
            "capabilities": ["prune_tool_result", "spill_tool_result"],
            "zero_token": True,
        }

    def start(self) -> None:
        self._threshold = self._config_int("tool_result_pruner.threshold_chars", 8192)
        self._head = self._config_int("tool_result_pruner.head_chars", 4096)
        self._tail = self._config_int("tool_result_pruner.tail_chars", 1024)
        spill_dir = self._config_str("tool_result_pruner.spill_dir", "logs/spilled")
        self._spill_dir = Path(spill_dir)
        self._spill_dir.mkdir(parents=True, exist_ok=True)

    def _config_int(self, key: str, default: int) -> int:
        if self.context is None:
            return default
        value = self.context.config.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _config_str(self, key: str, default: str) -> str:
        if self.context is None:
            return default
        value = self.context.config.get(key, default)
        return str(value) if value is not None else default

    def prune(self, tool_name: str, call_id: str, result: str) -> tuple[str, bool, Optional[str]]:
        """Prune or spill a tool result.

        Returns:
            (result, pruned, spill_path)
        """
        if len(result) <= self._threshold:
            return result, False, None

        session_id = self._get_session_id()
        spill_filename = f"{session_id}_{call_id}.txt"
        spill_path = self._spill_dir / spill_filename

        try:
            spill_path.write_text(result, encoding="utf-8")
        except OSError:
            spill_path = None

        pruned = result[: self._head] + f"\n\n... [truncated {len(result) - self._head - self._tail} chars] ...\n\n" + result[-self._tail :]

        self._emit(TOOL_RESULT_PRUNED, {
            "tool_name": tool_name,
            "call_id": call_id,
            "original_length": len(result),
            "pruned_length": len(pruned),
            "spill_path": str(spill_path) if spill_path else None,
        })

        if spill_path is not None:
            self._emit(TOOL_RESULT_SPILLED, {
                "tool_name": tool_name,
                "call_id": call_id,
                "spill_path": str(spill_path),
            })

        return pruned, True, str(spill_path) if spill_path else None

    def _get_session_id(self) -> str:
        if self.context is None:
            return "unknown"
        event_logger = self.context.plugins.get("event_logger")
        if event_logger is not None and hasattr(event_logger, "continuity"):
            return getattr(event_logger.continuity, "session_id", "unknown")
        return "unknown"

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.context is None:
            return
        try:
            self.context.events.emit(event_type, payload)
        except Exception:
            pass

    def health_check(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "plugin": self.name,
            "threshold_chars": self._threshold,
            "head_chars": self._head,
            "tail_chars": self._tail,
            "spill_dir": str(self._spill_dir),
        }
