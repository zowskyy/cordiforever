from __future__ import annotations

import pytest

from plugins.core.batch_cache import BatchCache


def test_batch_cache_miss_returns_none() -> None:
    cache = BatchCache()
    assert cache.get_cached("read_file", {"path": "a.txt"}) is None


def test_batch_cache_hit_returns_result() -> None:
    cache = BatchCache()
    cache.cache_result("read_file", {"path": "a.txt"}, "hello world")
    result = cache.get_cached("read_file", {"path": "a.txt"})
    assert result == "hello world"


def test_batch_cache_different_args_different_keys() -> None:
    cache = BatchCache()
    cache.cache_result("read_file", {"path": "a.txt"}, "hello")
    cache.cache_result("read_file", {"path": "b.txt"}, "world")
    assert cache.get_cached("read_file", {"path": "a.txt"}) == "hello"
    assert cache.get_cached("read_file", {"path": "b.txt"}) == "world"


def test_batch_cache_metrics() -> None:
    cache = BatchCache()
    cache.cache_result("read_file", {"path": "a.txt"}, "hello")
    cache.get_cached("read_file", {"path": "a.txt"})  # hit
    cache.get_cached("read_file", {"path": "b.txt"})  # miss
    metrics = cache.get_metrics()
    assert metrics["hits"] == 1
    assert metrics["misses"] == 1
    assert metrics["cache_size"] == 1
    assert metrics["hit_rate"] == 0.5


def test_batch_cache_health_check() -> None:
    cache = BatchCache()
    health = cache.health_check()
    assert health["healthy"] is True
    assert health["cache_size"] == 0
