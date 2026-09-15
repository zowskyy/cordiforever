from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from plugins.core.deterministic_knowledge import DeterministicKnowledgeStore


def test_deterministic_knowledge_ingest_and_query() -> None:
    store = DeterministicKnowledgeStore()
    entries = [
        {"id": "1", "title": "Python basics", "content": "Learn Python programming", "tags": ["lang"]},
        {"id": "2", "title": "Rust memory", "content": "Ownership and borrowing in Rust", "tags": ["lang"]},
        {"id": "3", "title": "Cooking pasta", "content": "Boil water and add pasta", "tags": ["food"]},
    ]
    added = store.ingest(entries)
    assert added == 3

    results = store.query("python programming", top_k=2)
    assert len(results) <= 2
    assert any(r["id"] == "1" for r in results)


def test_deterministic_knowledge_no_duplicate_ingest() -> None:
    store = DeterministicKnowledgeStore()
    entries = [
        {"id": "1", "title": "Python basics", "content": "Learn Python programming", "tags": ["lang"]},
    ]
    store.ingest(entries)
    added = store.ingest(entries)
    assert added == 0


def test_deterministic_knowledge_empty_query_returns_empty() -> None:
    store = DeterministicKnowledgeStore()
    store.ingest([{"id": "1", "title": "Python", "content": "Python programming", "tags": []}])
    results = store.query("asdf qwerty zxcv")
    assert results == []


def test_deterministic_knowledge_health_check() -> None:
    store = DeterministicKnowledgeStore()
    health = store.health_check()
    assert health["healthy"] is True
    assert health["entry_count"] == 0


def test_deterministic_knowledge_load_from_file() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        index = Path(tmp) / "index.json"
        index.write_text(
            '{"entries": [{"id": "1", "title": "Test", "content": "test content", "tags": []}]}',
            encoding="utf-8",
        )
        store = DeterministicKnowledgeStore(index_path=index)
        store.start()
        assert store._doc_count == 1
        results = store.query("test")
        assert len(results) == 1
