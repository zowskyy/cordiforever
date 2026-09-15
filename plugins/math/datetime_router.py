from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class DateResult:
    success: bool
    result: str = ""
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    operation: str | None = None
    args: dict[str, Any] = field(default_factory=dict)


class DateTimeRouterPlugin(EventDrivenPlugin):
    name = "datetime_router"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self.routes: list[tuple[re.Pattern[str], str, Any]] = []
        self._build_routes()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def route(self, query: str) -> DateResult:
        query = query.strip()
        for pattern, operation, extractor in self.routes:
            match = pattern.search(query)
            if match:
                try:
                    args = extractor(match)
                    return DateResult(success=True, result="", steps=[], operation=operation, args=args)
                except Exception as exc:
                    return DateResult(success=False, error=str(exc), operation=operation)
        return DateResult(success=False, error="No matching date/time route")

    def _build_routes(self) -> None:
        self.routes = [
            (re.compile(r"^today$", re.IGNORECASE), "today", lambda m: {}),
            (re.compile(r"^tomorrow$", re.IGNORECASE), "tomorrow", lambda m: {}),
            (re.compile(r"^yesterday$", re.IGNORECASE), "yesterday", lambda m: {}),
            (re.compile(r"^add\s+(-?\d+)\s+days?\s+to\s+(.+)$", re.IGNORECASE), "add_days", lambda m: {"days": int(m.group(1)), "date": m.group(2).strip()}),
            (re.compile(r"^(-?\d+)\s+days?\s+after\s+(.+)$", re.IGNORECASE), "add_days", lambda m: {"days": int(m.group(1)), "date": m.group(2).strip()}),
            (re.compile(r"^add\s+(-?\d+)\s+months?\s+to\s+(.+)$", re.IGNORECASE), "add_months", lambda m: {"months": int(m.group(1)), "date": m.group(2).strip()}),
            (re.compile(r"^add\s+(-?\d+)\s+years?\s+to\s+(.+)$", re.IGNORECASE), "add_years", lambda m: {"years": int(m.group(1)), "date": m.group(2).strip()}),
            (re.compile(r"^days?\s+between\s+(.+)\s+and\s+(.+)$", re.IGNORECASE), "days_between", lambda m: {"start": m.group(1).strip(), "end": m.group(2).strip()}),
            (re.compile(r"^what\s+day\s+is\s+(.+)$", re.IGNORECASE), "weekday", lambda m: {"date": m.group(1).strip()}),
            (re.compile(r"^format\s+(.+)\s+as\s+(.+)$", re.IGNORECASE), "format", lambda m: {"date": m.group(1).strip(), "format": m.group(2).strip()}),
        ]

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
