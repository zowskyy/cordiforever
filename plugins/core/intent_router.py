from __future__ import annotations

from core.intent_router import IntentRouter
from core.plugin import Plugin


class IntentRouterPlugin(Plugin):
    name = "intent_router"
    dependencies = ()

    def __init__(self, default_intent: str = "factual") -> None:
        super().__init__()
        self.default_intent = default_intent
        self._router = IntentRouter(default_intent=default_intent)

    def start(self) -> None:
        pass

    def route(self, query: str):
        return self._router.route(query)

    def classify_query(self, query: str) -> str:
        return self._router.classify_query(query)
