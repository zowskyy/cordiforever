from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.errors import ToolError
from core.messages import Message
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from tests.failure_recovery.harness import (
    DeterministicSandbox,
    FaultInjectingModel,
    FaultInjectingTools,
    Task,
)


def _run(tmp_path, responses, fault_config=None, max_rounds=3):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FaultInjectingModel(responses, fault_config))
    tf = {k: v for k, v in (fault_config or {}).items() if k.endswith("_timeout") or k.endswith("_malformed")}
    wo = (fault_config or {}).get("wrong_outputs", {})
    reg.register(FaultInjectingTools(tmp_path, fault_config=tf, wrong_outputs=wo))
    reg.register(AgentLoop(max_rounds=max_rounds))
    reg.start_all()
    try:
        return ctx.plugins["agent_loop"].run("task")
    finally:
        reg.stop_all()


def tc(name, args):
    return {"function": {"name": name, "arguments": args}}


def test_clean_baseline(tmp_path):
    r = _run(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ])
    assert r == "done"
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_timeout_recovery(tmp_path):
    r = _run(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], {"write_file_timeout": 1.0}, max_rounds=5)
    assert r == "done"


def test_malformed_args_recovery(tmp_path):
    r = _run(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], {"write_file_malformed": 1.0})
    assert r == "done"


def test_silent_wrong_output(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FaultInjectingModel([
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "a.txt"})]),
        Message("assistant", "done"),
    ])
    files = FaultInjectingTools(tmp_path, wrong_outputs={"read_file:a.txt": "WRONG"})
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()
    try:
        r = ctx.plugins["agent_loop"].run("read a file")
        assert r == "done"
    finally:
        reg.stop_all()


def test_retry_loop(tmp_path):
    r = _run(tmp_path, [
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."})]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."})]),
        Message("assistant", "done"),
    ], {"list_directory_timeout": 1.0}, max_rounds=5)
    assert r == "done"


def test_compound_failures(tmp_path):
    r = _run(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], {"write_file_timeout": 1.0, "write_file_malformed": 1.0}, max_rounds=5)
    assert r == "done"


def test_budget_exhaustion(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FaultInjectingModel([
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "failed"),
    ], {"write_file_timeout": 1.0}))
    reg.register(FaultInjectingTools(tmp_path, fault_config={"write_file_timeout": 1.0}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()
    try:
        with pytest.raises(ToolError, match="exceeded maximum"):
            ctx.plugins["agent_loop"].run("create a file")
    finally:
        reg.stop_all()


def test_seed_reproducibility(tmp_path):
    s1 = DeterministicSandbox(seed=123, tmp_path=tmp_path / "s1")
    s2 = DeterministicSandbox(seed=123, tmp_path=tmp_path / "s2")
    task = Task("repro", "create repro", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "repro.txt", "content": "repro"})]),
        Message("assistant", "repro done"),
    ], "repro done")
    sc1, sc2 = s1.run_task(task), s2.run_task(task)
    assert sc1.task_success == sc2.task_success
    assert sc1.steps_used == sc2.steps_used


def test_scorecard_metrics(tmp_path):
    sb = DeterministicSandbox(seed=1, tmp_path=tmp_path)
    task = Task("metrics", "metrics", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "m.txt", "content": "m"})]),
        Message("assistant", "done"),
    ], "done")
    sc = sb.run_task(task)
    assert sc.task_success is True
    assert sc.steps_used > 0
    assert sc.tool_calls_used >= 1
