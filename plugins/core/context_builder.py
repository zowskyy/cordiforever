from __future__ import annotations

from core.context_builder import ContextBuilder
from core.plugin import Plugin


class ContextBuilderPlugin(Plugin):
    name = "context_builder"
    dependencies = (
        "event_logger",
        "reality_projector",
        "semantic_memory",
        "summarizer",
        "logic_layer",
        "intent_router",
        "closed_loop",
        "episodic_memory",
    )

    def __init__(self, max_messages: int = 50) -> None:
        super().__init__()
        self.max_messages = max_messages
        self._builder = None

    def register(self, context) -> None:
        super().register(context)
        event_log = context.plugins.get("event_log")
        projector = context.plugins.get("reality_projector")
        semantic_memory = context.plugins.get("semantic_memory")
        summarizer = context.plugins.get("summarizer")
        logic_layer = context.plugins.get("logic_layer")
        intent_router = context.plugins.get("intent_router")
        closed_loop = context.plugins.get("closed_loop")
        if event_log is not None:
            self._builder = ContextBuilder(
                event_log=event_log,
                projector=projector,
                memory=context.plugins.get("episodic_memory"),
                semantic_memory=semantic_memory,
                summarizer=summarizer,
                logic_layer=logic_layer,
                intent_router=intent_router,
                closed_loop=closed_loop,
            )

    def start(self) -> None:
        pass

    def build(self, session_id, query="", max_messages=None):
        if self._builder is not None:
            return self._builder.build(session_id, query, max_messages or self.max_messages)
        return {"messages": [], "summary": "", "memory": "", "reality": {}, "route": None}

    def build_prompt(self, session_id, query) -> str:
        if self._builder is not None:
            return self._builder.build_prompt(session_id, query)
        return query
