from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .compaction import HybridPruningStrategy, PruningStrategy
from .messages import Message
from .summarizer import Summarizer


@dataclass
class PrunedContext:
    messages: list[Message]
    removed_count: int
    estimated_tokens_before: int
    estimated_tokens_after: int
    strategy: str


class ContextPruner:
    """Reduce effective KV cache pressure by pruning low-importance context.
    P1 FIX: Unified budget 30000 for 32768 ctx (leaves ~2768 headroom for 1.5B).
    This is the single authoritative pruning path. Summarizer.fold_messages
    delegates here to preserve invariant 2.6 (one pruning path, tool_calls preserved).
    """

    def __init__(self, max_messages: int = 40, token_budget: int = 3000, strategy: PruningStrategy | None = None):
        self.max_messages = max_messages
        self.token_budget = token_budget
        self._strategy = strategy or HybridPruningStrategy()

    def prune(self, messages: list[Message], task_state: dict[str, Any] | None = None) -> PrunedContext:
        before_tokens = Summarizer.estimate_tokens(str(messages))

        pruned = self._strategy.prune(
            messages=messages,
            max_messages=self.max_messages,
            token_budget=self.token_budget,
            task_state=task_state,
        )

        removed = len(messages) - len(pruned)
        strategy = getattr(self._strategy, "name", type(self._strategy).__name__) if removed > 0 else "none"

        return PrunedContext(
            messages=pruned,
            removed_count=removed,
            estimated_tokens_before=before_tokens,
            estimated_tokens_after=Summarizer.estimate_tokens(str(pruned)),
            strategy=strategy,
        )
