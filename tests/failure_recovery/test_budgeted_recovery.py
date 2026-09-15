from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.errors import ToolError
from core.messages import Message
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from tests.failure_recovery.harness import DeterministicSandbox, FaultInjectingModel, FaultInjectingTools, Task


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


def test_retry_budget_exhausted(tmp_path):
    ctx, reg = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "failed"),
    ], {"write_file_timeout": 1.0}, max_rounds=3)
    with pytest.raises(ToolError, match="exceeded maximum"):
        ctx.plugins["agent_loop"].run("create a file")
    reg.stop_all()


@pytest.mark.parametrize("max_rounds", [1, 5])
def test_budget_sweep(max_rounds, tmp_path):
    responses = [Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]) for _ in range(max_rounds)]
    responses.append(Message("assistant", "failed"))
    ctx, reg = _agent(tmp_path, responses, {"write_file_timeout": 1.0}, max_rounds=max_rounds)
    with pytest.raises(ToolError, match="exceeded maximum"):
        ctx.plugins["agent_loop"].run("create a file")
    reg.stop_all()


def test_budget_efficiency(tmp_path):
    sb = DeterministicSandbox(seed=42, tmp_path=tmp_path)
    task = Task("eff", "create file", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "eff.txt", "content": "eff"})]),
        Message("assistant", "done"),
    ], "done")
    sc = sb.run_task(task)
    assert sc.task_success and sc.steps_used >= 2 and sc.tool_calls_used >= 1
