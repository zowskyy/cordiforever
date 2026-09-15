from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass
class LogicRule:
    name: str
    query_types: Sequence[str]
    condition: Callable[[dict[str, Any]], bool]
    transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]


class LogicLayer:
    """Deterministic reasoning over retrieved memory structures."""

    def __init__(self) -> None:
        self._rules: list[LogicRule] = []

    def add_rule(self, rule: LogicRule) -> None:
        self._rules.append(rule)

    def query(self, notes: list[dict[str, Any]], query_type: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = context or {}
        results = []
        for rule in self._rules:
            if query_type in rule.query_types and rule.condition(ctx):
                results.extend(rule.transform(notes))
        return results

    def classify_query(self, query: str) -> str:
        q = query.lower()
        if any(word in q for word in ["must", "always", "never", "require", "constraint"]):
            return "constraint"
        if any(word in q for word in ["how to", "steps", "procedure", "process", "workflow"]):
            return "procedural"
        return "factual"
