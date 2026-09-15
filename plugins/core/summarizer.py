from __future__ import annotations

from core.summarizer import Summarizer
from core.plugin import Plugin


class SummarizerPlugin(Plugin):
    name = "summarizer"
    dependencies = ("ollama_model",)

    def __init__(self, model=None, max_length: int = 500) -> None:
        super().__init__()
        self._max_length = max_length
        self._model = model

    def register(self, context) -> None:
        super().register(context)
        if self._model is None:
            self._model = context.plugins.get("ollama_model")
        self._summarizer = Summarizer(model=self._model)

    def start(self) -> None:
        pass

    def summarize_events(self, events, max_length=None):
        return self._summarizer.summarize_events(events, max_length or self._max_length)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return Summarizer.estimate_tokens(text)

    @staticmethod
    def fold_messages(messages, max_messages=40, task_state=None):
        return Summarizer.fold_messages(messages, max_messages, task_state)
