"""
Semantic Router — extends the pool to catch natural language variants.

Additive: sits on top of regex routers, falls through to LLM on no match.
Uses only preexisting systems: EmbeddingModel + existing router functions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from core.plugin import EventDrivenPlugin


class SemanticRouter(EventDrivenPlugin):
    name = "semantic_router"
    dependencies = ("embedding_model",)

    CACHE_VERSION = "1.0"
    DEFAULT_THRESHOLD = 0.75

    def __init__(self, cache_path: str | Path | None = None, enabled: bool = False) -> None:
        super().__init__()
        self.enabled = enabled  # P0 FIX: default OFF to preserve zero-token pool guarantee
        self.cache_path = Path(cache_path) if cache_path else Path(".cache/semantic_router.json")
        self._embedder = None
        self._routes: list[dict[str, Any]] = []
        self._embeddings: dict[str, list[float]] = {}
        self._cache: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        if self.context is None:
            return
        # Allow enabling via config: config["semantic_router_enabled"]=True overrides constructor
        if self.context.config.get("semantic_router_enabled", self.enabled):
            self.enabled = True
        if not self.enabled:
            return
        self._embedder = self.context.plugins.get("embedding_model")
        self._build_routes()
        self._precompute()
        self._load_cache()

    def stop(self) -> None:
        self._save_cache()

    def route(self, query: str) -> str | None:
        # Gated: if disabled, never embed (preserves zero-token guarantee)
        if not self.enabled:
            return None
        if self.context is not None and not self.context.config.get("semantic_router_enabled", False):
            # also respect global config flag
            if not self.enabled:
                return None
        if self._embedder is None or not self._routes:
            return None
        query = query.strip()
        if not query:
            return None
        cached = self._cache.get(query)
        if cached is not None:
            route_id = cached.get("route_id", "")
            score = cached.get("score", 0.0)
            threshold = cached.get("threshold", self.DEFAULT_THRESHOLD)
            if score >= threshold:
                return self._execute(route_id, query)
            return None
        embedding = self._embedder.embed(query)
        if not embedding:
            return None
        best_id, best_score = self._find_best(embedding)
        route = next((r for r in self._routes if r["id"] == best_id), None)
        threshold = route.get("threshold", self.DEFAULT_THRESHOLD) if route else self.DEFAULT_THRESHOLD
        self._cache[query] = {
            "route_id": best_id,
            "score": best_score,
            "threshold": threshold,
        }
        if best_score >= threshold:
            return self._execute(best_id, query)
        return None

    def _build_routes(self) -> None:
        self._routes = [
            {"id": "math_derivative", "examples": ["take the derivative of x^2", "differentiate sin(x)", "find d/dx of x^3 + 2x", "derive x**2*cos(x)"], "delegate": "math", "threshold": 0.70},
            {"id": "math_integral", "examples": ["what's the integral of x^2?", "integrate sin(x) dx", "find the antiderivative of cos(x)", "integral of e^x from 0 to 1"], "delegate": "math", "threshold": 0.70},
            {"id": "math_solve", "examples": ["solve x^2 - 4 = 0", "find the roots of x^2 + 2x + 1", "what is x in 2x + 3 = 7?", "solve for x: 3x - 5 = 10"], "delegate": "math", "threshold": 0.75},
            {"id": "math_evaluate", "examples": ["evaluate x^2 + 1 at x = 3", "what is 2x + 3 when x = 5?", "plug in x = 2 into x^3"], "delegate": "math", "threshold": 0.70},
            {"id": "math_simplify", "examples": ["simplify x^2/x", "reduce x^2 + 2x + x", "combine like terms"], "delegate": "math", "threshold": 0.70},
            {"id": "math_expand", "examples": ["expand (x + 1)^2", "multiply out (x-2)(x+3)", "distribute 2x(x + 1)"], "delegate": "math", "threshold": 0.70},
            {"id": "math_factor", "examples": ["factor x^2 + 5x + 6", "factorize x^2 - 4"], "delegate": "math", "threshold": 0.70},
            {"id": "math_limit", "examples": ["limit sin(x)/x as x approaches 0", "what is the limit of 1/x as x goes to infinity?", "lim x→0 of sin(x)/x"], "delegate": "math", "threshold": 0.70},
            {"id": "datetime_today", "examples": ["what's today?", "what is the current date?", "today's date", "what day is it"], "delegate": "datetime", "threshold": 0.80},
            {"id": "datetime_add_days", "examples": ["add 5 days to 2024-01-01", "what is 3 weeks from today?", "10 days from now"], "delegate": "datetime", "threshold": 0.75},
            {"id": "datetime_days_between", "examples": ["days between 2024-01-01 and 2024-01-10", "how many days from Jan 1 to Jan 10?"], "delegate": "datetime", "threshold": 0.75},
            {"id": "units_convert", "examples": ["convert 100 km to miles", "100 km in miles", "how many pounds is 5 kg?", "convert 10 meters to feet"], "delegate": "units", "threshold": 0.75},
        ]

    def _precompute(self) -> None:
        if not self._routes or not self._embedder:
            return
        texts = [" ".join(route["examples"]) for route in self._routes]
        embeddings = self._embedder.embed_batch(texts)
        for route, embedding in zip(self._routes, embeddings):
            if embedding:
                self._embeddings[route["id"]] = embedding

    def _find_best(self, embedding: list[float]) -> tuple[str, float]:
        best_id = ""
        best_score = 0.0
        for route_id, route_embedding in self._embeddings.items():
            score = self._cosine(embedding, route_embedding)
            if score > best_score:
                best_score = score
                best_id = route_id
        return best_id, best_score

    def _execute(self, route_id: str, query: str) -> str | None:
        route = next((r for r in self._routes if r["id"] == route_id), None)
        if route is None:
            return None
        delegate = route.get("delegate")
        if delegate == "math":
            return self._delegate_math(query)
        if delegate == "datetime":
            return self._delegate_datetime(query)
        if delegate == "units":
            return self._delegate_units(query)
        return None

    def _delegate_math(self, query: str) -> str | None:
        try:
            from plugins.agent.routers import try_math_router
            return try_math_router(query, self.context)
        except Exception:
            return None

    def _delegate_datetime(self, query: str) -> str | None:
        try:
            from plugins.agent.routers import try_datetime_router
            return try_datetime_router(query, self.context)
        except Exception:
            return None

    def _delegate_units(self, query: str) -> str | None:
        try:
            from plugins.agent.routers import try_units_router
            return try_units_router(query, self.context)
        except Exception:
            return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    def _load_cache(self) -> None:
        if self.cache_path is None or not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version") == self.CACHE_VERSION:
                # Support nested entries (new) and flat (old) for backward compat
                if "entries" in data and isinstance(data["entries"], dict):
                    self._cache = data["entries"]
                else:
                    self._cache = {k: v for k, v in data.items() if k != "version"}
        except (json.JSONDecodeError, OSError):
            pass

    def _save_cache(self) -> None:
        if self.cache_path is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": self.CACHE_VERSION, "entries": self._cache}
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def on_turn_start(self, event: Any) -> None:
        pass

    def on_tool_result(self, event: Any) -> None:
        pass

    def on_turn_end(self, event: Any) -> None:
        pass
