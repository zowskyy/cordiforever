from __future__ import annotations

import json

from core.context_pruner import ContextPruner, PrunedContext
from core.messages import Message


def _msg(role, content="", tool_calls=None):
    return Message(role=role, content=content, tool_calls=tool_calls)


def test_pruner_no_op_when_under_limit():
    pruner = ContextPruner(max_messages=10)
    messages = [_msg("user", "hi"), _msg("assistant", "hello")]
    result = pruner.prune(messages)
    assert result.removed_count == 0
    assert result.strategy == "none"


def test_pruner_removes_low_importance():
    pruner = ContextPruner(max_messages=3)
    messages = [
        _msg("user", "q1"),
        _msg("system", "repair msg failed"),
        _msg("tool", '{"success": false}'),
        _msg("user", "q2"),
        _msg("assistant", "final"),
    ]
    result = pruner.prune(messages)
    assert result.removed_count > 0
    assert len(result.messages) <= 3
    assert result.messages[-1].content == "final"


def test_pruner_preserves_recent():
    pruner = ContextPruner(max_messages=3)
    messages = [
        _msg("user", "old"),
        _msg("assistant", "mid"),
        _msg("tool", '{"success": true}'),
        _msg("user", "recent"),
        _msg("assistant", "done"),
    ]
    result = pruner.prune(messages)
    assert result.messages[-1].content == "done"
    assert result.messages[-2].content == "recent"


def test_pruner_returns_metrics():
    pruner = ContextPruner(max_messages=2)
    messages = [
        _msg("user", "a"),
        _msg("system", "b"),
        _msg("tool", '{"success": true}'),
        _msg("user", "c"),
    ]
    result = pruner.prune(messages)
    assert isinstance(result, PrunedContext)
    assert result.removed_count > 0
    assert result.estimated_tokens_after < result.estimated_tokens_before
    assert result.strategy == "hybrid"


def test_pruner_token_pass_when_under_message_limit():
    """33k window: under the message cap, a few LARGE messages can still
    exceed the token budget. The token pass drops lowest-score messages
    (leading system + two most recent protected) until within budget, and
    keeps assistant+tool_calls alive while a cheaper target exists."""
    pruner = ContextPruner(max_messages=100, token_budget=1000)
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
    result = pruner.prune(messages)
    assert result.estimated_tokens_after <= 1000
    assert result.removed_count == 1
    assert result.strategy == "hybrid"
    assert result.messages[0].role == "system"        # leading system protected
    assert result.messages[-1].content == "done"      # two most recent protected
    assert not any("x" * 100 in (m.content or "") for m in result.messages)
    assert sum(1 for m in result.messages if m.tool_calls) == 2  # single-pruner preservation
