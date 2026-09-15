from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.plugin import EventDrivenPlugin


@dataclass
class MathResult:
    success: bool
    result: str = ""
    steps: list[str] = field(default_factory=list)
    error: str | None = None
    operation: str | None = None
    args: dict[str, Any] = field(default_factory=dict)


class MathPipelinePlugin(EventDrivenPlugin):
    name = "math_pipeline"
    dependencies = ("math_router",)

    def __init__(self) -> None:
        super().__init__()
        self._router = None
        self._engine = None
        self._parameter_extractor = None

    def start(self) -> None:
        if self.context is None:
            return
        self._router = self.context.plugins.get("math_router")
        self._engine = self.context.plugins.get("symbolic_engine")
        self._parameter_extractor = self.context.plugins.get("parameter_extractor")

    def stop(self) -> None:
        pass

    def run(self, query: str) -> MathResult:
        if self._router is None or self._engine is None:
            return MathResult(success=False, error="math_router_not_available")
        if self._parameter_extractor is not None:
            query = self._parameter_extractor.extract_math_expression(query)
        segments = self._split(query)
        if len(segments) <= 1:
            return self._execute_segment(query)
        all_steps: list[str] = []
        last_result: str | None = None
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            if self._parameter_extractor is not None:
                segment = self._parameter_extractor.extract_math_expression(segment)
            if last_result is not None and self._needs_expression(segment):
                segment = self._inject_expression(segment, last_result)
            result = self._execute_segment(segment)
            if not result.success:
                return result
            all_steps.extend(result.steps)
            last_result = result.result
        final = last_result if last_result else (all_steps[-1] if all_steps else "")
        return MathResult(success=True, result=final, steps=all_steps, operation="pipeline")

    def _execute_segment(self, query: str) -> MathResult:
        route_result = self._router.route(query)
        if not route_result.success:
            return route_result
        if route_result.operation == "arithmetic":
            kwargs = self._parse_arithmetic(query)
        else:
            kwargs = self._parse_operation(query, route_result.operation)
        result = self._engine.compute(route_result.operation, **kwargs)
        result.args = route_result.args
        return result

    def _split(self, query: str) -> list[str]:
        separators = [
            r"\s+and\s+then\s+",
            r"\s+then\s+",
            r"\s+followed\s+by\s+",
            r"\s+after\s+that\s+",
            r"\s*;\s*",
        ]
        pattern = "|".join(separators)
        parts = re.split(pattern, query, flags=re.IGNORECASE)
        cleaned = []
        for p in parts:
            p = p.strip()
            if p:
                lowered = p.lower()
                for prefix in ["then", "and then", "followed by", "after that"]:
                    if lowered.startswith(prefix):
                        p = p[len(prefix):].strip()
                        break
                cleaned.append(p)
        return cleaned

    def _needs_expression(self, query: str) -> bool:
        lowered = query.lower()
        return any(lowered.startswith(kw) for kw in [
            "evaluate", "eval", "derive", "differentiate", "derivative of",
            "integrate", "integral of", "solve", "solve_linear", "solve_quadratic",
            "limit", "lim", "trig_simplify", "trigsimp",
            "det", "determinant of", "inverse", "inverse of",
            "eigenvalues", "eigenvalue", "trace", "rank", "expand", "factor", "simplify"
        ])

    def _inject_expression(self, segment: str, last_result: str) -> str:
        lowered = segment.lower()
        for kw in ["evaluate", "eval", "derive", "differentiate", "derivative of",
                    "integrate", "integral of", "solve", "solve_linear", "solve_quadratic",
                    "limit", "lim", "trig_simplify", "trigsimp",
                    "det", "determinant of", "inverse", "inverse of",
                    "eigenvalues", "eigenvalue", "trace", "rank", "expand", "factor", "simplify"]:
            if lowered.startswith(kw):
                rest = segment[len(kw):].strip()
                return f"{kw} {last_result} {rest}"
        return segment

    def _parse_arithmetic(self, query: str) -> dict[str, Any]:
        match = re.search(r"^([\d\.]+)\s*([\+\-\*\/])\s*([\d\.]+)$", query.strip())
        if not match:
            raise ValueError(f"Cannot parse arithmetic: {query}")
        return {"left": match.group(1), "op": match.group(2), "right": match.group(3)}

    def _parse_operation(self, query: str, operation: str) -> dict[str, Any]:
        if operation == "derivative":
            m = re.match(r"^(?:derive|differentiate|derivative\s+of)\s+(.+)$", query.strip(), re.IGNORECASE)
            return {"expression": m.group(1).strip() if m else query}
        if operation == "integral":
            m = re.match(r"^(?:integrate|integral\s+of)\s+(.+?)(?:\s+(d[xyz]|dt))?$", query.strip(), re.IGNORECASE)
            return {"expression": m.group(1).strip() if m else query}
        if operation == "limit":
            m = re.match(r"^(?:limit|lim)\s+(.+?)(?:\s+as\s+(\w+)\s*[-–]>?\s*(-?\d+(?:\.\d+)?))?$", query.strip(), re.IGNORECASE)
            kwargs: dict[str, Any] = {"expression": m.group(1).strip() if m else query}
            if m and m.group(2) and m.group(3):
                kwargs["variable"] = m.group(2)
                kwargs["point"] = float(m.group(3))
            return kwargs
        if operation == "solve":
            m = re.match(r"^(?:solve|find\s+roots?\s+of|roots?\s+of)\s+(.+)$", query.strip(), re.IGNORECASE)
            return {"expression": m.group(1).strip() if m else query}
        if operation == "solve_linear":
            m = re.match(r"^solve\s+linear\s+(.+)$", query.strip(), re.IGNORECASE)
            return {"expression": m.group(1).strip() if m else query}
        if operation == "solve_quadratic":
            m = re.match(r"^solve\s+quadratic\s+(.+)$", query.strip(), re.IGNORECASE)
            return {"expression": m.group(1).strip() if m else query}
        if operation == "trig_simplify":
            m = re.match(r"^(?:trig\s*simplify|trigsimp)\s+(.+)$", query.strip(), re.IGNORECASE)
            return {"expression": m.group(1).strip() if m else query}
        if operation == "evaluate":
            m = re.match(r"^(?:evaluate|eval)\s+(.+?)(?:\s+at\s+(\w+)\s*=\s*(.+))?$", query.strip(), re.IGNORECASE)
            kwargs = {"expression": m.group(1).strip() if m else query}
            if m and m.group(2) and m.group(3):
                kwargs["variable"] = m.group(2)
                kwargs["point"] = m.group(3).strip()
            return kwargs
        if operation in {"determinant", "inverse", "eigenvalues", "trace", "rank"}:
            m = re.match(r"^(?:" + "|".join([
                "det", "determinant\\s+of",
                "inverse", "inverse\\s+of",
                "eigenvalues?", "trace", "rank"
            ]) + r")\s+(.+)$", query.strip(), re.IGNORECASE)
            raw = m.group(1).strip() if m else query
            return {"matrix": self._safe_matrix_parse(raw)}
        return {"expression": query}

    @staticmethod
    def _safe_matrix_parse(raw: str) -> list[list[float]]:
        import ast, json
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
