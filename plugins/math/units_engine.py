from __future__ import annotations

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


class UnitsEnginePlugin(EventDrivenPlugin):
    name = "units_engine"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self._ureg = None

    def start(self) -> None:
        try:
            import pint
            self._ureg = pint.UnitRegistry()
        except ImportError:
            self._ureg = None

    def stop(self) -> None:
        pass

    def compute(self, operation: str, **kwargs: Any) -> UnitResult:
        if self._ureg is None:
            return UnitResult(success=False, error="pint_unavailable", operation=operation)
        try:
            if operation == "convert":
                return self._convert(**kwargs)
            return UnitResult(success=False, error=f"Unknown units operation: {operation}")
        except Exception as exc:
            return UnitResult(success=False, error=str(exc), operation=operation)

    def _convert(self, **kwargs: Any) -> UnitResult:
        value = float(kwargs["value"])
        from_unit = kwargs["from_unit"]
        to_unit = kwargs["to_unit"]
        q = self._ureg(f"{value} {from_unit}")
        result = q.to(to_unit)
        result_str = f"{result.magnitude:.6g}"
        return UnitResult(
            success=True,
            result=f"{result_str} {to_unit}",
            steps=[f"{value} {from_unit} = {result_str} {to_unit}"],
            operation="convert"
        )

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
