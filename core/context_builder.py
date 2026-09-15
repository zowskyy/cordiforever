from __future__ import annotations

from typing import Any, Optional

from .events import Event
from .event_log import EventLog
from .closed_loop_retrieval import ClosedLoopRetrieval, RetrievalResult
from .intent_router import IntentRouter, Route
from .logic_layer import LogicLayer
from .memory import EpisodicMemory
from .reality import RealityProjector
from .semantic_memory import SemanticMemory
from .summarizer import Summarizer


class ContextBuilder:
    """Builds model context from projections, memory, and reality."""

    def __init__(
        self,
        event_log: EventLog,
        projector: RealityProjector,
        memory: Optional[EpisodicMemory] = None,
        semantic_memory: Optional[SemanticMemory] = None,
        summarizer: Optional[Summarizer] = None,
        logic_layer: Optional[LogicLayer] = None,
        intent_router: Optional[IntentRouter] = None,
        closed_loop: Optional[ClosedLoopRetrieval] = None,
    ) -> None:
        self._event_log = event_log
        self._projector = projector
        self._memory = memory
        self._semantic_memory = semantic_memory
        self._summarizer = summarizer
        self._logic_layer = logic_layer
        self._intent_router = intent_router or IntentRouter()
        self._closed_loop = closed_loop

    def build(
        self,
        session_id: str,
        query: str = "",
        max_messages: int = 50,
    ) -> dict[str, Any]:
        reality = self._projector.get_reality(session_id)
        route = self._intent_router.route(query) if query else Route(intent="factual", confidence=0.0, retrieval_mode="note_first")

        memory_context = ""
        if self._semantic_memory and query:
            if self._closed_loop:
                result = self._closed_loop.retrieve(session_id, query, route.retrieval_mode)
                memory_context = self._format_retrieval_result(result)
            else:
                memory_context = self._legacy_retrieve(session_id, query, route.retrieval_mode)

            if self._logic_layer and memory_context:
                notes = self._semantic_memory.retrieve_notes(session_id, limit=10)
                logic_results = self._logic_layer.query(notes, route.intent, route.context)
                if logic_results:
                    memory_context += "\nDerived:\n"
                    for result in logic_results:
                        memory_context += f"- {result.get('content', result)}\n"

        messages = reality.messages[-max_messages:]

        summary_parts = []
        if reality.files_read:
            summary_parts.append(f"Files read: {', '.join(sorted(reality.files_read))}")
        if reality.files_written:
            summary_parts.append(f"Files written: {', '.join(sorted(reality.files_written))}")
        if reality.errors:
            summary_parts.append(f"Recent errors: {len(reality.errors)}")

        return {
            "messages": messages,
            "summary": "; ".join(summary_parts) if summary_parts else "No previous activity",
            "memory": memory_context,
            "reality": reality.summary(),
            "route": route,
        }

    def _legacy_retrieve(self, session_id: str, query: str, retrieval_mode: str) -> str:
        if retrieval_mode == "note_first":
            notes = self._semantic_memory.retrieve_notes(session_id, limit=5)
            if notes:
                return "Known facts:\n" + "\n".join(f"- {n['content']}" for n in notes)
        elif retrieval_mode == "episode_first":
            episodes = self._semantic_memory.retrieve_episodes(session_id, query, top_k=5)
            if episodes:
                return "Relevant episodes:\n" + "\n".join(f"- {ep['text'][:200]}" for ep in episodes)
        else:
            results = self._semantic_memory.hybrid_retrieve(session_id, query, top_k=5)
            if results:
                return "Relevant memory:\n" + "\n".join(
                    f"- [NOTE] {r['data']['content']}" if r["type"] == "note" else f"- [EPISODE] {r['data']['text'][:200]}"
                    for r in results
                )
        return ""

    def _format_retrieval_result(self, result: RetrievalResult) -> str:
        parts: list[str] = []
        if result.notes:
            parts.append("Known facts:\n" + "\n".join(f"- {n['content']}" for n in result.notes))
        if result.episodes:
            parts.append("Relevant episodes:\n" + "\n".join(f"- {ep['text'][:200]}" for ep in result.episodes))
        if result.evidence_gap and result.gap_reason:
            parts.append(f"[retrieval] Evidence gap detected: {result.gap_reason}. Escalated to hybrid retrieval.")
        return "\n\n".join(parts)

    def build_prompt(self, session_id: str, query: str) -> str:
        context = self.build(session_id, query)

        parts = []
        if context["summary"] != "No previous activity":
            parts.append(f"Context: {context['summary']}")
        if context["memory"]:
            parts.append(context["memory"])

        if parts:
            return "\n\n".join(parts) + f"\n\nUser: {query}"
        return query
