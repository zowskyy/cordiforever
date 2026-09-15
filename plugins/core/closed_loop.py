from __future__ import annotations

from core.closed_loop_retrieval import ClosedLoopRetrieval
from core.plugin import Plugin


class ClosedLoopRetrievalPlugin(Plugin):
    name = "closed_loop"
    dependencies = ("event_logger", "semantic_memory")

    def __init__(self) -> None:
        super().__init__()
        self._closed_loop = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        semantic_memory = context.plugins.get("semantic_memory")
        if event_log is not None and semantic_memory is not None:
            self._closed_loop = ClosedLoopRetrieval(event_log, semantic_memory)

    def start(self) -> None:
        pass

    def retrieve(self, session_id, query, route_mode, top_k=5):
        if self._closed_loop is not None:
            return self._closed_loop.retrieve(session_id, query, route_mode, top_k)
        from core.closed_loop_retrieval import RetrievalResult
        return RetrievalResult(mode="none", notes=[], episodes=[])
