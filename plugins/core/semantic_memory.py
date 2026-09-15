from __future__ import annotations

from core.semantic_memory import SemanticMemory
from core.plugin import Plugin


class SemanticMemoryPlugin(Plugin):
    name = "semantic_memory"
    dependencies = ("event_logger",)

    def __init__(self) -> None:
        super().__init__()
        self._semantic = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        if event_log is not None:
            self._semantic = SemanticMemory(event_log)

    def start(self) -> None:
        pass

    def index_events(self, session_id: str) -> None:
        if self._semantic is not None:
            self._semantic.index_events(session_id)

    def add_note(self, session_id, event_id, note_type, content, confidence=1.0) -> None:
        if self._semantic is not None:
            self._semantic.add_note(session_id, event_id, note_type, content, confidence)

    def retrieve_notes(self, session_id, note_type=None, limit=10):
        if self._semantic is not None:
            return self._semantic.retrieve_notes(session_id, note_type, limit)
        return []

    def retrieve_episodes(self, session_id, query, top_k=5):
        if self._semantic is not None:
            return self._semantic.retrieve_episodes(session_id, query, top_k)
        return []

    def hybrid_retrieve(self, session_id, query, top_k=5):
        if self._semantic is not None:
            return self._semantic.hybrid_retrieve(session_id, query, top_k)
        return []

    def reconsolidate(self, session_id, new_notes) -> None:
        if self._semantic is not None:
            self._semantic.reconsolidate(session_id, new_notes)
