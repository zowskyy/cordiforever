from __future__ import annotations

from typing import Protocol

from core.messages import Message
from core.summarizer import Summarizer


class PruningStrategy:
    name = "base"

    def prune(self, messages: list[Message], max_messages: int, token_budget: int, task_state: dict[str, object] | None = None) -> list[Message]:
        raise NotImplementedError()


class TokenFirstStrategy(PruningStrategy):
    name = "token_first"

    def prune(self, messages: list[Message], max_messages: int, token_budget: int, task_state: dict[str, object] | None = None) -> list[Message]:
        pruned = list(messages)
        while Summarizer.estimate_tokens(str(pruned)) > token_budget and len(pruned) > 3:
            candidates = [m for i, m in enumerate(pruned) if i > 0 and i < len(pruned) - 2]
            if not candidates:
                break
            worst = min(candidates, key=lambda m: self._score(m, pruned.index(m), len(pruned), task_state))
            pruned.remove(worst)
        return pruned

    def _score(self, msg: Message, index: int, total: int, task_state: dict[str, object] | None) -> float:
        role = msg.role or ""
        if role == "assistant" and msg.tool_calls:
            return 1.5
        if role == "user":
            return 1.0
        if role == "tool":
            try:
                import json
                payload = json.loads(msg.content)
                if payload.get("success"):
                    return 0.8
            except (json.JSONDecodeError, AttributeError):
                pass
            return 0.4
        if role == "system":
            return 0.6
        recency = index / max(total, 1)
        return 0.1 + recency


class MessageFirstStrategy(PruningStrategy):
    name = "message_first"

    def prune(self, messages: list[Message], max_messages: int, token_budget: int, task_state: dict[str, object] | None = None) -> list[Message]:
        if len(messages) <= max_messages:
            return list(messages)
        keep = max_messages
        return messages[-keep:]


class HybridPruningStrategy(PruningStrategy):
    name = "hybrid"

    def prune(self, messages: list[Message], max_messages: int, token_budget: int, task_state: dict[str, object] | None = None) -> list[Message]:
        pruned = list(messages)

        if len(messages) > max_messages:
            scored = []
            for i, msg in enumerate(messages):
                score = self._score(msg, i, len(messages), task_state)
                scored.append((score, i, msg))

            scored.sort(key=lambda x: x[0])
            keep_count = max_messages
            keep_indices = {i for _, i, _ in scored[-keep_count:]}
            keep_indices.add(len(messages) - 1)
            keep_indices.add(len(messages) - 2)

            pruned = [m for i, m in enumerate(messages) if i in keep_indices]
            pruned.sort(key=lambda m: messages.index(m))

        while Summarizer.estimate_tokens(str(pruned)) > token_budget and len(pruned) > 3:
            candidates = [m for i, m in enumerate(pruned) if i > 0 and i < len(pruned) - 2]
            if not candidates:
                break
            worst = min(candidates, key=lambda m: self._score(m, pruned.index(m), len(pruned), task_state))
            pruned.remove(worst)

        return pruned

    def _score(self, msg: Message, index: int, total: int, task_state: dict[str, object] | None) -> float:
        role = msg.role or ""
        if role == "user":
            return 2.0
        if role == "assistant" and msg.tool_calls:
            return 1.5
        if role == "tool":
            try:
                import json
                payload = json.loads(msg.content)
                if payload.get("success"):
                    return 1.0
            except (json.JSONDecodeError, AttributeError):
                pass
            return 0.5
        if role == "system":
            if msg.content and "failed" in msg.content.lower():
                return 0.3
            return 0.8
        recency = index / max(total, 1)
        return 0.1 + recency


class StrategyRegistry:
    _strategies: dict[str, PruningStrategy] = {}

    @classmethod
    def register(cls, strategy: PruningStrategy) -> None:
        cls._strategies[strategy.name] = strategy

    @classmethod
    def get(cls, name: str) -> PruningStrategy:
        if name not in cls._strategies:
            raise KeyError(f"Unknown pruning strategy: {name}")
        return cls._strategies[name]

    @classmethod
    def names(cls) -> list[str]:
        return list(cls._strategies.keys())


StrategyRegistry.register(TokenFirstStrategy())
StrategyRegistry.register(MessageFirstStrategy())
StrategyRegistry.register(HybridPruningStrategy())
