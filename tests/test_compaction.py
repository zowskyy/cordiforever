from __future__ import annotations

from core.compaction import HybridPruningStrategy, MessageFirstStrategy, TokenFirstStrategy
from core.context_pruner import ContextPruner
from core.messages import Message


def _msg(role, content="", tool_calls=None):
    return Message(role=role, content=content, tool_calls=tool_calls)


def test_token_first_strategy_drops_by_token_budget():
    strategy = TokenFirstStrategy()
    big_tool = '{"success": true, "data": "' + "x" * 8000 + '"}'
    tc = {"id": "1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
    messages = [
        _msg("system", "system prompt"),
        _msg("user", "read the file"),
        _msg("assistant", "", tool_calls=[tc]),
        _msg("tool", big_tool),
        _msg("user", "and read another"),
        _msg("assistant", "", tool_calls=[tc]),
        _msg("tool", "small result"),
        _msg("assistant", "done"),
    ]
    pruned = strategy.prune(messages, max_messages=100, token_budget=1000)
    assert len(pruned) < len(messages)
    assert not any("x" * 100 in (m.content or "") for m in pruned)


def test_message_first_strategy_keeps_recent():
    strategy = MessageFirstStrategy()
    messages = [
        _msg("user", "old"),
        _msg("system", "mid"),
        _msg("tool", '{"success": true}'),
        _msg("user", "recent"),
        _msg("assistant", "done"),
    ]
    pruned = strategy.prune(messages, max_messages=3, token_budget=10000)
    assert len(pruned) == 3
    assert pruned[-1].content == "done"
    assert pruned[-2].content == "recent"


def test_hybrid_strategy_combines_message_and_token():
    strategy = HybridPruningStrategy()
    messages = [
        _msg("system", "s"),
        _msg("user", "u1"),
        _msg("assistant", "a1"),
        _msg("tool", '{"success": true}'),
        _msg("user", "u2"),
    ]
    pruned = strategy.prune(messages, max_messages=3, token_budget=1000)
    assert len(pruned) <= 3


def test_strategy_registry_round_trip():
    from core.compaction import StrategyRegistry
    assert "hybrid" in StrategyRegistry.names()
    assert "token_first" in StrategyRegistry.names()
    assert "message_first" in StrategyRegistry.names()
    assert isinstance(StrategyRegistry.get("hybrid"), HybridPruningStrategy)


def test_context_pruner_uses_registered_strategy():
    from core.compaction import MessageFirstStrategy, StrategyRegistry
    StrategyRegistry.register(MessageFirstStrategy())
    pruner = ContextPruner(max_messages=2, strategy=StrategyRegistry.get("message_first"))
    messages = [
        _msg("user", "a"),
        _msg("system", "b"),
        _msg("tool", '{"success": true}'),
        _msg("user", "c"),
    ]
    result = pruner.prune(messages)
    assert result.strategy == "message_first"
