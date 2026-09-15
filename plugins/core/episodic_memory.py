from __future__ import annotations

from core.memory import EpisodicMemory
from core.plugin import Plugin


class EpisodicMemoryPlugin(Plugin):
    name = "episodic_memory"
    dependencies = ("event_logger",)

    def __init__(self, model=None) -> None:
        super().__init__()
        self._model = model
        self._memory = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        if event_log is not None:
            self._memory = EpisodicMemory(event_log, model=self._model)

    def start(self) -> None:
        pass

    def remember(self, event, summary, tags=None) -> None:
        if self._memory is not None:
            self._memory.remember(event, summary, tags)

    def recall(self, session_id, query=None, limit=10):
        if self._memory is not None:
            return self._memory.recall(session_id, query, limit)
        return []

    def decay(self, session_id, keep_limit=100) -> None:
        if self._memory is not None:
            self._memory.decay(session_id, keep_limit)
