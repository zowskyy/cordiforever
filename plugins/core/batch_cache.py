from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from core.plugin import Plugin


class BatchCache(Plugin):
    """Zero-token content-hash cache for tool calls.

    Memoizes tool results by content hash of (tool_name, arguments).
    Cache misses pass through; hits return cached results without
    executing the tool again.
    """

    name = "batch_cache"
    dependencies = ()

    def __init__(self, max_size: int = 1024) -> None:
        super().__init__()
        self._cache: dict[str, str] = {}
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def start(self) -> None:
        self._cache = {}
        self._hits = 0
        self._misses = 0

    def stop(self) -> None:
        self._cache = {}

    def _hash_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        payload = f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get_cached(self, tool_name: str, arguments: dict[str, Any]) -> Optional[str]:
        key = self._hash_tool_call(tool_name, arguments)
        result = self._cache.get(key)
        if result is not None:
            self._hits += 1
        else:
            self._misses += 1
        return result

    def cache_result(self, tool_name: str, arguments: dict[str, Any], result: str) -> None:
        key = self._hash_tool_call(tool_name, arguments)
        if len(self._cache) >= self._max_size:
            # Evict first inserted (FIFO approximation)
            first_key = next(iter(self._cache))
            del self._cache[first_key]
        self._cache[key] = result

    def get_metrics(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "cache_size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }

    def health_check(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "plugin": self.name,
            "cache_size": len(self._cache),
        }
