"""
Multi-Domain Router — routes each fragment to its optimal handler.

Uses existing deterministic routers where possible.
Returns unresolved fragments for LLM fallback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.plugin import Plugin
from plugins.agent.query_splitter import Fragment, QuerySplitter


@dataclass
class DomainResult:
    fragment: Fragment
    domain: str
    response: str | None


@dataclass
class MultiDomainResult:
    results: list[DomainResult]
    has_unresolved: bool = False


class MultiDomainRouter(Plugin):
    name = "multi_domain_router"
    dependencies = ("query_splitter",)

    def __init__(self) -> None:
        super().__init__()
        self._splitter: QuerySplitter | None = None

    def start(self) -> None:
        if self.context is not None:
            self._splitter = self.context.plugins.get("query_splitter")

    def route_multi(self, text: str, context: Any) -> MultiDomainResult | None:
        if self._splitter is None:
            return None

        fragments = self._splitter.split(text)
        if len(fragments) <= 1:
            return None

        results: list[DomainResult] = []
        has_unresolved = False

        for frag in fragments:
            response = self._try_route(frag, context)
            if response is None:
                has_unresolved = True
            results.append(DomainResult(fragment=frag, domain=frag.domain, response=response))

        return MultiDomainResult(results=results, has_unresolved=has_unresolved)

    def _try_route(self, frag: Fragment, context: Any) -> str | None:
        from plugins.agent.routers import try_datetime_router, try_math_router, try_units_router

        if frag.domain == "math":
            return try_math_router(frag.text, context)
        if frag.domain == "datetime":
            return try_datetime_router(frag.text, context)
        if frag.domain == "units":
            return try_units_router(frag.text, context)
        return None
