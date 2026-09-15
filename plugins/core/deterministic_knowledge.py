from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from core.plugin import Plugin


@dataclass
class TrajectoryEntry:
    """Structured implementation trajectory for self-improvement."""

    id: str
    category: str
    title: str
    problem: str
    source_pattern: str
    adaptation: str
    implementation_files: List[str]
    tests_added: List[str]
    invariants_preserved: List[str]
    verification_result: str
    confidence: float
    reusability: str
    timestamp: str
    decision_reasoning: str = ""
    alternatives_considered: Optional[List[str]] = None
    trade_offs: str = ""
    lessons_learned: str = ""
    qwen_1_5b_impact: str = ""


class DeterministicKnowledgeStore(Plugin):
    """Zero-token TF-IDF knowledge store for lite profile.

    Uses regex tokenization and TF-IDF scoring to retrieve relevant
    knowledge entries without any embedding or LLM calls.
    """

    name = "deterministic_knowledge"
    dependencies = ()

    def __init__(self, index_path: str | Path | None = None) -> None:
        super().__init__()
        self._index_path = Path(index_path) if index_path else None
        self._entries: list[dict[str, Any]] = []
        self._df: Counter = Counter()
        self._doc_count = 0
        self._loaded = False
        self._trajectory_index: dict[str, TrajectoryEntry] = {}
        self._trajectory_path = Path("knowledge/chat_trajectories.jsonl")

    def start(self) -> None:
        if self._index_path and self._index_path.exists():
            self._load_index(self._index_path)
        self._load_trajectories()

    def stop(self) -> None:
        self._entries = []
        self._df.clear()
        self._doc_count = 0
        self._loaded = False
        self._trajectory_index = {}

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9_]+", text.lower())

    def _tfidf_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        tf = Counter(doc_tokens)
        score = 0.0
        for token in query_tokens:
            if token not in tf:
                continue
            idf = math.log((self._doc_count + 1) / (self._df[token] + 1)) + 1.0
            score += (tf[token] / len(doc_tokens)) * idf
        return score

    def _load_index(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        entries = data.get("entries", [])
        self._entries = list(entries)
        self._doc_count = len(self._entries)
        self._df.clear()
        for entry in self._entries:
            text = f"{entry.get('title', '')} {entry.get('content', '')} {' '.join(entry.get('tags', []))}"
            tokens = set(self._tokenize(text))
            for token in tokens:
                self._df[token] += 1
        self._loaded = True

    def _load_trajectories(self) -> None:
        """Load implementation trajectories from exported chat history."""
        if not self._trajectory_path.exists():
            return
        try:
            with open(self._trajectory_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    self._trajectory_index[data["id"]] = TrajectoryEntry(**data)
        except (OSError, json.JSONDecodeError):
            return

    def ingest(self, entries: list[dict[str, Any]]) -> int:
        """Ingest new entries into the index.

        Args:
            entries: List of dicts with at least 'id', 'title', 'content'.

        Returns:
            Number of new entries added.
        """
        known_ids = {e["id"] for e in self._entries if "id" in e}
        new_entries = [e for e in entries if e.get("id") and e["id"] not in known_ids]
        if not new_entries:
            return 0

        for entry in new_entries:
            self._entries.append(entry)
            text = f"{entry.get('title', '')} {entry.get('content', '')} {' '.join(entry.get('tags', []))}"
            tokens = set(self._tokenize(text))
            for token in tokens:
                self._df[token] += 1

        self._doc_count = len(self._entries)
        self._loaded = True
        return len(new_entries)

    def query(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Query the index for the most relevant entries.

        Args:
            query_text: Natural language query.
            top_k: Maximum number of results to return.

        Returns:
            List of entries sorted by relevance score (descending).
        """
        if not self._entries or not self._loaded:
            return []

        query_tokens = self._tokenize(query_text)
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self._entries:
            text = f"{entry.get('title', '')} {entry.get('content', '')} {' '.join(entry.get('tags', []))}"
            doc_tokens = self._tokenize(text)
            score = self._tfidf_score(query_tokens, doc_tokens)
            if score > 0:
                scored.append((score, {**entry, "score": round(score, 4)}))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def query_trajectory(self, problem_keywords: List[str]) -> Optional[TrajectoryEntry]:
        """Find implementation trajectory matching problem keywords.

        Args:
            problem_keywords: Keywords describing the problem to solve.

        Returns:
            Best matching trajectory, or None if no match found.
        """
        best_match = None
        best_score = 0.0

        for entry in self._trajectory_index.values():
            score = float(
                sum(
                    1
                    for kw in problem_keywords
                    if kw.lower()
                    in entry.problem.lower()
                    or kw.lower() in entry.title.lower()
                    or kw.lower() in entry.category.lower()
                )
            )
            if score > best_score:
                best_score = score
                best_match = entry

        return best_match if best_score > 0 else None

    def get_similar_trajectories(
        self, keywords: List[str], limit: int = 3
    ) -> List[TrajectoryEntry]:
        """Get top N trajectories matching keywords, sorted by relevance.

        Args:
            keywords: Keywords to search for.
            limit: Maximum number of results.

        Returns:
            List of matching trajectories sorted by relevance.
        """
        scored: list[tuple[float, TrajectoryEntry]] = []
        for entry in self._trajectory_index.values():
            search_text = " ".join(
                [
                    entry.problem,
                    entry.title,
                    entry.category,
                    " ".join(entry.implementation_files),
                ]
            ).lower()
            score = float(sum(1 for kw in keywords if kw.lower() in search_text))
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    def get_all_trajectories(self) -> List[TrajectoryEntry]:
        """Return all loaded trajectories."""
        return list(self._trajectory_index.values())

    def health_check(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "plugin": self.name,
            "entry_count": len(self._entries),
            "loaded": self._loaded,
            "trajectory_count": len(self._trajectory_index),
        }

