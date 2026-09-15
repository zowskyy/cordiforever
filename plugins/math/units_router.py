from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class UnitResult:
    success: bool
    result: str = ""
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    operation: str | None = None
    args: dict[str, Any] = field(default_factory=dict)


class UnitsRouterPlugin(EventDrivenPlugin):
    name = "units_router"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self.routes: list[tuple[re.Pattern[str], str, Any]] = []
        self._build_routes()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def route(self, query: str) -> UnitResult:
        query = query.strip()
        for pattern, operation, extractor in self.routes:
            match = pattern.search(query)
            if match:
                try:
                    args = extractor(match)
                    return UnitResult(success=True, result="", steps=[], operation=operation, args=args)
                except Exception as exc:
                    return UnitResult(success=False, error=str(exc), operation=operation)
        return UnitResult(success=False, error="No matching units route")

    def _build_routes(self) -> None:
        self.routes = [
            (re.compile(r"^convert\s+(-?\d+(?:\.\d+)?)\s+(\w+)\s+to\s+(\w+)$", re.IGNORECASE), "convert", lambda m: {"value": float(m.group(1)), "from_unit": m.group(2), "to_unit": m.group(3)}),
            (re.compile(r"^(-?\d+(?:\.\d+)?)\s+(\w+)\s+in\s+(\w+)$", re.IGNORECASE), "convert", lambda m: {"value": float(m.group(1)), "from_unit": m.group(2), "to_unit": m.group(3)}),
            (re.compile(r"^(-?\d+(?:\.\d+)?)\s+(\w+)\s+to\s+(\w+)$", re.IGNORECASE), "convert", lambda m: {"value": float(m.group(1)), "from_unit": m.group(2), "to_unit": m.group(3)}),
        ]

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
