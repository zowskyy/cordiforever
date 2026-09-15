"""Array failure recovery tests.

These tests verify that the array-related failure scenarios are handled
correctly: tool timeouts, malformed arguments, wrong outputs, and budget
exhaustion for array tasks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.errors import ToolError
from core.messages import Message
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from tests.failure_recovery.harness import FaultInjectingModel, FaultInjectingTools, Task
from tests.benchmarks.tasks import ALL_ARRAY_TASKS


def tc(name, args):
    return {"function": {"name": name, "arguments": args}}


def _agent(tmp_path, responses, fault_config=None, max_rounds=3):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FaultInjectingModel(responses, fault_config))
    tf = {k: v for k, v in (fault_config or {}).items() if k.endswith("_timeout") or k.endswith("_malformed")}
    wo = (fault_config or {}).get("wrong_outputs", {})
    reg.register(FaultInjectingTools(tmp_path, fault_config=tf, wrong_outputs=wo))
    reg.register(AgentLoop(max_rounds=max_rounds))
    reg.start_all()
    return ctx, reg


def test_array_filter_recovery_from_timeout(tmp_path):
    """Filter task should recover when write_file times out, then succeeds."""
    import random as _random
    _random.seed(42)  # deterministic for recovery test
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const active = items.filter(x => x.active);"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const active = items.filter(x => x.active);"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const active = items.filter(x => x.active);"})]),
        Message("assistant", "done"),
    ]
    ctx, reg = _agent(tmp_path, responses, {"write_file_timeout": 0.5}, max_rounds=5)
    try:
        result = ctx.plugins["agent_loop"].run("Filter items by active flag")
        assert "done" in result.lower()
    finally:
        reg.stop_all()


def test_array_sort_malformed_args_recovery(tmp_path):
    """Sort task should recover when first call has missing args."""
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const sorted = items.sort((a,b) => a - b);"})]),
        Message("assistant", "done"),
    ]
    ctx, reg = _agent(tmp_path, responses, {"write_file_malformed": 0.0}, max_rounds=5)
    try:
        result = ctx.plugins["agent_loop"].run("Sort items by name")
        assert "done" in result.lower()
    finally:
        reg.stop_all()


def test_array_aggregate_silent_wrong_output_recovery(tmp_path):
    """Aggregate task should handle wrong outputs gracefully."""
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const total = items.reduce((s, i) => s + i, 0);"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "data.js"})]),
        Message("assistant", "done"),
    ]
    ctx, reg = _agent(
        tmp_path, responses,
        {"wrong_outputs": {"read_file:data.js": "WRONG RESULT"}},
        max_rounds=5,
    )
    try:
        result = ctx.plugins["agent_loop"].run("Sum all values in the array")
        assert "done" in result.lower()
    finally:
        reg.stop_all()


def test_array_budget_exhaustion_with_retries(tmp_path):
    """Array task that exceeds retry budget should raise ToolError."""
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "bad"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "bad"})]),
        Message("assistant", "failed"),
    ]
    ctx, reg = _agent(tmp_path, responses, {"write_file_timeout": 1.0}, max_rounds=2)
    with pytest.raises(ToolError, match="exceeded maximum"):
        ctx.plugins["agent_loop"].run("Delete items from the list")
    reg.stop_all()


def test_array_compound_failures_recovery(tmp_path):
    """Array task with multiple fault types should eventually recover."""
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "items.sort();"})]),
        Message("assistant", "done"),
    ]
    fault_config = {
        "write_file_timeout": 0.5,
        "write_file_malformed": 0.3,
    }
    ctx, reg = _agent(tmp_path, responses, fault_config, max_rounds=5)
    try:
        result = ctx.plugins["agent_loop"].run("Sort the array of numbers")
        # Should complete despite faults
        assert "done" in result.lower()
    finally:
        reg.stop_all()


def test_array_empty_collection_handling_in_recovery(tmp_path):
    """Recovery should handle empty array scenarios in model responses."""
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const result = [].filter(x => x > 0)"})]),
        Message("assistant", "done"),
    ]
    ctx, reg = _agent(tmp_path, responses, max_rounds=3)
    try:
        result = ctx.plugins["agent_loop"].run("Filter an empty array")
        assert "done" in result.lower()
        content = (tmp_path / "data.js").read_text(encoding="utf-8")
        assert "[]" in content
    finally:
        reg.stop_all()


def test_array_helper_no_interference_on_failure(tmp_path):
    """ArrayHelper faults should not interfere with standard failure recovery."""
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg
    from plugins.agent.array_helper import ArrayHelper

    ctx = Ctx()
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.js", "content": "const x = items.filter(p => p.active)"})]),
        Message("assistant", "done"),
    ]
    reg.register(FaultInjectingModel(responses, {"write_file_timeout": 1.0}))
    reg.register(FaultInjectingTools(tmp_path, fault_config={"write_file_timeout": 0.5}))
    reg.register(ArrayHelper())
    reg.register(AgentLoop(max_rounds=5))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("Filter active items")
        assert "done" in result.lower()
    finally:
        reg.stop_all()
