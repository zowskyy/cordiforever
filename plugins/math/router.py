from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from core.plugin import EventDrivenPlugin


@dataclass
class Route:
    pattern: re.Pattern[str]
    operation: str
    extractor: Callable[[re.Match[str]], dict[str, Any]]


@dataclass
class MathResult:
    success: bool
    result: str = ""
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    operation: str | None = None
    args: dict[str, Any] = field(default_factory=dict)


class MathRouterPlugin(EventDrivenPlugin):
    name = "math_router"
    dependencies = ()

    def __init__(self) -> None:
        super().__init__()
        self.routes: list[Route] = []
        self._build_routes()

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def route(self, query: str) -> MathResult:
        query = query.strip()
        for route in self.routes:
            match = route.pattern.search(query)
            if match:
                try:
                    args = route.extractor(match)
                    return MathResult(success=True, result="", steps=[], operation=route.operation, args=args)
                except Exception as exc:
                    return MathResult(success=False, error=str(exc), operation=route.operation)
        return MathResult(success=False, error="No matching math route")

    def _build_routes(self) -> None:
        self.routes = [
            Route(re.compile(r"^([\d\.]+)\s*([\+\-\*\/])\s*([\d\.]+)$", re.IGNORECASE), "arithmetic", self._extract_arithmetic),
            Route(re.compile(r"^(derive|differentiate|derivative\s+of)\s+(.+)$", re.IGNORECASE), "derivative", self._extract_expr),
            Route(re.compile(r"^(integrate|integral\s+of)\s+(.+?)(?:\s+(d[xyz]|dt))?$", re.IGNORECASE), "integral", self._extract_expr),
            Route(re.compile(r"^(expand)\s+(.+)$", re.IGNORECASE), "expand", self._extract_expr),
            Route(re.compile(r"^(factor)\s+(.+)$", re.IGNORECASE), "factor", self._extract_expr),
            Route(re.compile(r"^(simplify)\s+(.+)$", re.IGNORECASE), "simplify", self._extract_expr),
            Route(re.compile(r"^(trig\s*simplify|trigsimp|trig_simplify)\s+(.+)$", re.IGNORECASE), "trig_simplify", self._extract_expr),
            Route(re.compile(r"^solve\s+linear\s+(.+)$", re.IGNORECASE), "solve_linear", self._extract_expr),
            Route(re.compile(r"^solve\s+quadratic\s+(.+)$", re.IGNORECASE), "solve_quadratic", self._extract_expr),
            Route(re.compile(r"^(solve|find\s+roots?\s+of|roots?\s+of)\s+(.+)$", re.IGNORECASE), "solve", self._extract_expr),
            Route(re.compile(r"^(limit|lim)\s+(.+?)(?:\s+as\s+(\w+)\s*[-–]>?\s*(-?\d+(?:\.\d+)?))?$", re.IGNORECASE), "limit", self._extract_limit),
            Route(re.compile(r"^(det|determinant\s+of)\s+(.+)$", re.IGNORECASE), "determinant", self._extract_matrix),
            Route(re.compile(r"^(inverse|inverse\s+of)\s+(.+)$", re.IGNORECASE), "inverse", self._extract_matrix),
            Route(re.compile(r"^(eigenvalues?)\s+(.+)$", re.IGNORECASE), "eigenvalues", self._extract_matrix),
            Route(re.compile(r"^(trace)\s+(.+)$", re.IGNORECASE), "trace", self._extract_matrix),
            Route(re.compile(r"^(rank)\s+(.+)$", re.IGNORECASE), "rank", self._extract_matrix),
            Route(re.compile(r"^(evaluate|eval)\s+(.+?)\s+at\s+(\w+)\s*=\s*(.+)$", re.IGNORECASE), "evaluate", self._extract_evaluate),
        ]

    def _extract_arithmetic(self, match: re.Match[str]) -> dict[str, Any]:
        return {"left": match.group(1), "op": match.group(2), "right": match.group(3)}

    def _extract_expr(self, match: re.Match[str]) -> dict[str, Any]:
        group = match.group(2) if match.lastindex >= 2 else match.group(1)
        return {"expression": group.strip()}

    def _extract_limit(self, match: re.Match[str]) -> dict[str, Any]:
        expr = match.group(2).strip()
        kwargs: dict[str, Any] = {"expression": expr}
        if match.group(3) and match.group(4):
            kwargs["variable"] = match.group(3)
            kwargs["point"] = float(match.group(4))
        return kwargs

    def _extract_matrix(self, match: re.Match[str]) -> dict[str, Any]:
        raw = match.group(2).strip()
        return {"matrix": self._safe_matrix_parse(raw)}

    def _extract_evaluate(self, match: re.Match[str]) -> dict[str, Any]:
        expr = match.group(2).strip()
        kwargs: dict[str, Any] = {"expression": expr}
        if match.group(3) and match.group(4):
            kwargs["variable"] = match.group(3)
            kwargs["point"] = match.group(4).strip()
        return kwargs

    @staticmethod
    def _safe_matrix_parse(raw: str) -> list[list[float]]:
        cleaned = raw.replace("'", '"')
        try:
            data = json.loads(cleaned)
            if isinstance(data, list) and all(isinstance(row, list) for row in data):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            tree = ast.parse(raw, mode='eval')
            if isinstance(tree.body, ast.List):
                return [[float(c) for c in row.elts] for row in tree.body.elts if isinstance(row, ast.List)]
        except Exception:
            pass
        raise ValueError(f"Cannot parse matrix: {raw}")

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
