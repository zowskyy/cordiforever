from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.core.deterministic_knowledge import DeterministicKnowledgeStore, TrajectoryEntry


REPO = Path(__file__).resolve().parents[1]
TRAJECTORY_FILE = REPO / "knowledge" / "chat_trajectories.jsonl"


def _load_store() -> DeterministicKnowledgeStore:
    store = DeterministicKnowledgeStore()
    store.start()
    return store


def test_trajectories_loaded() -> None:
    store = _load_store()
    try:
        trajectories = store.get_all_trajectories()
        assert len(trajectories) >= 6
        assert any(t.id == "session_integrity_hash_chain" for t in trajectories)
        assert any(t.id == "deterministic_knowledge_store" for t in trajectories)
        assert any(t.id == "batch_cache_memoization" for t in trajectories)
    finally:
        store.stop()


def test_query_trajectory_finds_match() -> None:
    store = _load_store()
    try:
        result = store.query_trajectory(["hash", "integrity", "session"])
        assert result is not None
        assert result.id == "session_integrity_hash_chain"
    finally:
        store.stop()


def test_query_trajectory_no_match_returns_none() -> None:
    store = _load_store()
    try:
        result = store.query_trajectory(["quantum", "blockchain", "unrelated"])
        assert result is None
    finally:
        store.stop()


def test_get_similar_trajectories_returns_sorted() -> None:
    store = _load_store()
    try:
        results = store.get_similar_trajectories(["test", "plugin", "security"], limit=3)
        assert len(results) <= 3
        assert any(
            "security" in t.category.lower() or "security" in t.problem.lower() for t in results
        )
    finally:
        store.stop()


def test_trajectory_has_required_fields() -> None:
    store = _load_store()
    try:
        for trajectory in store.get_all_trajectories():
            assert trajectory.id is not None
            assert trajectory.title is not None
            assert trajectory.problem is not None
            assert trajectory.source_pattern is not None
            assert trajectory.adaptation is not None
            assert trajectory.implementation_files is not None
            assert trajectory.verification_result is not None
            assert 0.0 <= trajectory.confidence <= 1.0
            assert trajectory.reusability in ["High", "Medium", "Low"]
    finally:
        store.stop()


def test_trajectory_invariants_preserved() -> None:
    valid_invariants = {
        "zero-token",
        "zero-drag",
        "protected-files",
        "event-taxonomy",
        "plugin-contract",
        "calibration-immutability",
    }
    store = _load_store()
    try:
        for trajectory in store.get_all_trajectories():
            if trajectory.invariants_preserved:
                for invariant in trajectory.invariants_preserved:
                    assert invariant in valid_invariants
    finally:
        store.stop()
