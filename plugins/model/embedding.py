"""
Embedding Plugin — provides deterministic text embeddings via Ollama.

Single responsibility: convert text -> vector.
Used by SemanticRouter and any other component needing embeddings.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from core.plugin import Plugin


class EmbeddingModel(Plugin):
    name = "embedding_model"
    dependencies = ("ollama_model",)

    def __init__(
        self,
        cache_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self.cache_path = Path(cache_path) if cache_path else Path(".cache/embeddings.json")
        self._model = None
        self._cache: dict[str, list[float]] = {}
        self._hits = 0
        self._misses = 0

    def start(self) -> None:
        if self.context is None:
            return
        self._model = self.context.plugins.get("ollama_model")
        self._load_cache()

    def stop(self) -> None:
        self._save_cache()

    def embed(self, text: str) -> list[float]:
        if not text or not isinstance(text, str):
            return []
        text = text.strip()
        if not text:
            return []
        cached = self._cache.get(text)
        if cached is not None:
            self._hits += 1
            return cached
        self._misses += 1
        if self._model is None:
            return []
        try:
            vector = self._model.embed(text)
        except Exception:
            return []
        if vector:
            vector = self._normalize(vector)
            self._cache[text] = vector
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        uncached: list[str] = []
        for text in texts:
            cached = self._cache.get(text)
            if cached is not None:
                self._hits += 1
                results.append(cached)
            else:
                self._misses += 1
                uncached.append(text)
        if uncached and self._model is not None:
            try:
                batch_results = [self._model.embed(t) for t in uncached]
            except Exception:
                batch_results = []
            for text, vector in zip(uncached, batch_results):
                if vector:
                    vector = self._normalize(vector)
                    self._cache[text] = vector
            for text in uncached:
                results.append(self._cache.get(text, []))
        return results

    def similarity(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        mag = math.sqrt(sum(x * x for x in vector))
        if mag == 0:
            return vector
        return [x / mag for x in vector]

    def get_metrics(self) -> dict[str, Any]:
        return {
            "cache_size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(self._hits + self._misses, 1),
        }

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version") == "1.0":
                # Support both old flat format and new nested "entries" format (avoids "version" key collision)
                if "entries" in data and isinstance(data["entries"], dict):
                    self._cache = {k: v for k, v in data["entries"].items() if isinstance(v, list)}
                else:
                    self._cache = {k: v for k, v in data.items() if k not in ("version", "entries") and isinstance(v, list)}
        except (json.JSONDecodeError, OSError):
            pass

    def _save_cache(self) -> None:
        if not self.cache_path.parent.exists():
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        # P1 FIX: nested entries avoids collision if user text is "version"
        payload = {"version": "1.0", "entries": self._cache}
        try:
            self.cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
