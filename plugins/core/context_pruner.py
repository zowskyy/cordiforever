from __future__ import annotations

from core.calibration import calibration_from_context
from core.context_pruner import ContextPruner
from core.plugin import Plugin


class ContextPrunerPlugin(Plugin):
    name = "context_pruner"
    dependencies = ()

    def __init__(self, max_messages: int | None = None, token_budget: int | None = None) -> None:
        super().__init__()
        # Defaults resolve from the model calibration table (core.context) at
        # register() time — no model-specific literals live here.
        self.max_messages = max_messages
        self.token_budget = token_budget
        self._pruner: ContextPruner | None = None

    def register(self, context) -> None:
        super().register(context)
        cal = calibration_from_context(context)
        if self.token_budget is None:
            self.token_budget = cal["pruner_budget"]
        if self.max_messages is None:
            self.max_messages = cal["max_messages"]
        self._pruner = ContextPruner(max_messages=self.max_messages, token_budget=self.token_budget)

    def start(self) -> None:
        pass

    def prune(self, messages, task_state=None):
        if self._pruner is None:
            cal = calibration_from_context(self.context)
            self._pruner = ContextPruner(max_messages=self.max_messages or cal["max_messages"], token_budget=self.token_budget or cal["pruner_budget"])
        return self._pruner.prune(messages, task_state)
