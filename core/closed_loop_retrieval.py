from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .event_log import EventLog
from .semantic_memory import SemanticMemory


@dataclass
class RetrievalResult:
    mode: str
    notes: list[dict[str, Any]]
    episodes: list[dict[str, Any]]
    evidence_gap: bool = False
    gap_reason: str | None = None


class ClosedLoopRetrieval:
    def __init__(self, event_log: EventLog, semantic_memory: SemanticMemory) -> None:
        self._event_log = event_log
        self._semantic_memory = semantic_memory
        self._min_note_conf = 0.4
        self._min_ep_score = 0.2
        self._min_total = 2

    def retrieve(self, session_id: str, query: str, route_mode: str, top_k: int = 5) -> RetrievalResult:
        notes, episodes = [], []
        if route_mode == "note_first":
            notes = self._semantic_memory.retrieve_notes(session_id, limit=top_k)
            if self._gap(notes, episodes):
                episodes = self._semantic_memory.retrieve_episodes(session_id, query, top_k)
                return RetrievalResult(mode="hybrid", notes=notes, episodes=episodes, evidence_gap=True, gap_reason="insufficient_notes")
            return RetrievalResult(mode="note_first", notes=notes, episodes=episodes)
        if route_mode == "episode_first":
            episodes = self._semantic_memory.retrieve_episodes(session_id, query, top_k)
            if self._gap(notes, episodes):
                notes = self._semantic_memory.retrieve_notes(session_id, limit=top_k)
                return RetrievalResult(mode="hybrid", notes=notes, episodes=episodes, evidence_gap=True, gap_reason="insufficient_episodes")
            return RetrievalResult(mode="episode_first", notes=notes, episodes=episodes)
        notes = self._semantic_memory.retrieve_notes(session_id, limit=top_k)
        episodes = self._semantic_memory.retrieve_episodes(session_id, query, top_k)
        return RetrievalResult(mode="hybrid", notes=notes, episodes=episodes)

    def _gap(self, notes, episodes):
        if notes and all(n.get("confidence", 0) >= self._min_note_conf for n in notes):
            return False
        if episodes and all(e.get("score", 0) >= self._min_ep_score for e in episodes):
            return False
        return len(notes) + len(episodes) < self._min_total
