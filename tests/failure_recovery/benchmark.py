from __future__ import annotations

import json
import tempfile
from pathlib import Path

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
    summarize,
)


def tc(name, args):
    return {"function": {"name": name, "arguments": args}}


TASKS = [
    Task("clean_write", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done"),
    Task("clean_read", "read a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "a.txt"})]),
        Message("assistant", "done"),
    ], "done"),
    Task("timeout_recovery", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done", {"write_file_timeout": 0.3}),
    Task("malformed_args", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done", {"write_file_malformed": 0.0}),
    Task("silent_wrong", "read a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "a.txt"})]),
        Message("assistant", "done"),
    ], "done", {"wrong_outputs": {"read_file:a.txt": "WRONG"}}),
    Task("retry_loop", "list files", [
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."})]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."})]),
        Message("assistant", "done"),
    ], "done", {"list_directory_timeout": 0.3}),
    Task("compound", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done", {"write_file_timeout": 0.3, "write_file_malformed": 0.3}),
    Task("budget_exhaustion", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "failed"),
    ], "done", {"write_file_timeout": 0.3}),
    Task("adaptive_replan", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "readonly/a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done", {"write_file_timeout": 0.3}),
    Task("context_folding", "write many files", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": f"f{i}.txt", "content": f"data{i}"}) for i in range(60)]),
        Message("assistant", "done"),
    ], "done"),
    Task("multi_file_refactor", "refactor code", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "src/a.py", "content": "old"}), tc("write_file", {"path": "src/b.py", "content": "old"}), tc("write_file", {"path": "src/c.py", "content": "old"})]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "src"}), tc("read_file", {"path": "src/a.py"}), tc("read_file", {"path": "src/b.py"}), tc("read_file", {"path": "src/c.py"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "src/a.py", "content": "new"}), tc("write_file", {"path": "src/b.py", "content": "new"}), tc("write_file", {"path": "src/c.py", "content": "new"})]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "src"})]),
        Message("assistant", "done"),
    ], "done", total_steps=12),
    Task("constraint_search_replace", "search and replace", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "data.txt", "content": "foo bar foo"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "data.txt"}), tc("write_file", {"path": "data.txt", "content": "baz bar baz"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "data.txt"}), tc("write_file", {"path": "data2.txt", "content": "foo baz foo"})]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."})]),
        Message("assistant", "done"),
    ], "done", total_steps=10),
    Task("native_runtime_ops", "file lifecycle", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "lifecycle.txt", "content": "v1"})]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."}), tc("read_file", {"path": "lifecycle.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "lifecycle.txt", "content": "v2"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "lifecycle.txt"}), tc("list_directory", {"path": "."})]),
        Message("assistant", "done"),
    ], "done", total_steps=10),
    Task("partial_completion", "optional steps", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "req1.txt", "content": "required"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "opt1.txt", "content": "optional"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "req2.txt", "content": "required"})]),
        Message("assistant", "done"),
    ], "done", total_steps=15, optional_steps=10),
    Task("efficiency_sensitive", "budget task", [
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."}), tc("write_file", {"path": "eff.txt", "content": "data"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "eff.txt"}), tc("write_file", {"path": "eff.txt", "content": "updated"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "eff.txt"})]),
        Message("assistant", "done"),
    ], "done", total_steps=12),
]


def _agent(tmp_path, responses, fault_config=None):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FaultInjectingModel(responses, fault_config)
    tf = {k: v for k, v in (fault_config or {}).items() if k.endswith("_timeout") or k.endswith("_malformed")}
    wo = (fault_config or {}).get("wrong_outputs", {})
    files = FaultInjectingTools(tmp_path, fault_config=tf, wrong_outputs=wo)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=5))
    reg.start_all()
    return ctx, reg


def run(seed=42):
    tmp = Path(tempfile.mkdtemp())
    sb = DeterministicSandbox(seed=seed, tmp_path=tmp)
    return summarize([sb.run_task(t, "retry") for t in TASKS])


def run_folding_comparison(seed=42):
    tmp = Path(tempfile.mkdtemp())
    sb = DeterministicSandbox(seed=seed, tmp_path=tmp)
    folding_task = next(t for t in TASKS if t.name == "context_folding")
    sb_no_fold = DeterministicSandbox(seed=seed, tmp_path=tmp / "no_fold")
    sb_fold = DeterministicSandbox(seed=seed, tmp_path=tmp / "fold")
    sc_no_fold = sb_no_fold.run_task(folding_task, "retry")
    sc_fold = sb_fold.run_task(folding_task, "retry")
    return {
        "no_fold_tool_calls": sc_no_fold.tool_calls_used,
        "fold_tool_calls": sc_fold.tool_calls_used,
        "no_fold_steps": sc_no_fold.steps_used,
        "fold_steps": sc_fold.steps_used,
    }


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=2))
    checks = [
        ("success", r.get("success_rate", 0), ">=", 0.80),
        ("recovery", r.get("avg_recovery_rate", 0), ">=", 0.60),
        ("silent", r.get("avg_silent_failure_rate", 0), "<=", 0.10),
        ("loop", r.get("avg_loop_rate", 0), "<=", 0.05),
        ("invalid", r.get("avg_invalid_call_rate", 0), "<=", 0.05),
    ]
    passed = sum(1 for _, v, op, t in checks if eval(f"{v} {op} {t}"))
    print(f"\nScore: {passed}/5 benchmarks met")

    print("\n--- Phase 3 Long-Horizon Metrics ---")
    print(f"Partial completion: {r.get('avg_partial_completion', 0):.2%}")
    print(f"Efficiency: {r.get('avg_efficiency', 0):.2f}")
    print(f"Recovery latency: {r.get('avg_recovery_latency', 0):.1f} steps")
    print(f"Cascade rate: {r.get('avg_cascade_rate', 0):.2%}")

    print("\n--- Context Folding Comparison ---")
    comparison = run_folding_comparison()
    print(json.dumps(comparison, indent=2))
