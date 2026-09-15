"""
Aggregate Response — combines multi-domain results into a single answer.

Formats each domain's response with clear labels and separators.
Zero cost — pure string formatting.
"""
from __future__ import annotations

from typing import Any

from core.plugin import Plugin
from plugins.agent.multi_domain_router import DomainResult


class AggregateResponse(Plugin):
    name = "aggregate_response"
    dependencies = ()

    def aggregate(self, results: list[DomainResult]) -> str:
        if not results:
            return ""
        if len(results) == 1:
            return self._clean_response(results[0].response or "")

        parts: list[str] = []
        for r in results:
            if r.response:
                cleaned = self._clean_response(r.response)
                parts.append(f"[{r.domain}] {cleaned}")

        return "\n\n".join(parts)

    def _clean_response(self, response: str) -> str:
        lines = response.strip().splitlines()
        if not lines:
            return response.strip()
        result_line = lines[-1].strip()
        if result_line.startswith("Result: "):
            return result_line[len("Result: "):]
        if result_line.startswith("Result:"):
            return result_line[len("Result:"):].strip()
        return response.strip()
