"""
Per-task diagnostic runner using ONLY preexisting systems.

Uses the existing DeterministicSandbox + FaultInjectingModel + FaultInjectingTools
to run each task in complete isolation and report:
  - success/failure
  - tool call sequence
  - root-cause category
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from core.context import Context
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
    ], "done", {"write_file_timeout": 1.0}),
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
    ], "done", {"list_directory_timeout": 1.0}),
    Task("compound", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done", {"write_file_timeout": 1.0, "write_file_malformed": 1.0}),
    Task("budget_exhaustion", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "failed"),
    ], "done", {"write_file_timeout": 1.0}),
    Task("adaptive_replan", "write hello to a.txt", [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "readonly/a.txt", "content": "hello"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "a.txt", "content": "hello"})]),
        Message("assistant", "done"),
    ], "done", {"write_file_timeout": 1.0}),
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


def _payload(event):
    raw = event.payload
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _run_single(task: Task, workspace: Path):
    """Run one task using the existing harness pattern."""
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FaultInjectingModel(task.model_responses, task.fault_config)
    tf = {k: v for k, v in (task.fault_config or {}).items() if k.endswith("_timeout") or k.endswith("_malformed")}
    wo = (task.fault_config or {}).get("wrong_outputs", {})
    reg.register(EventLogger(workspace / "test.db"))
    reg.register(model)
    reg.register(FaultInjectingTools(workspace, fault_config=tf, wrong_outputs=wo))
    reg.register(AgentLoop(max_rounds=20))
    reg.start_all()
    try:
        result = ctx.plugins["agent_loop"].run(task.user_input)
        el = ctx.plugins["event_logger"]
        cont = el.continuity
        session_id = cont.session_id if hasattr(cont, "session_id") else "default"
        events = el.event_log.get_session_events(session_id)
        return ctx, reg, result, events
    except Exception as exc:
        return ctx, reg, exc, []
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()


def diagnose(task: Task):
    workspace = Path(tempfile.mkdtemp())
    ctx, reg, result, events = _run_single(task, workspace)

    tool_invocations = [e for e in events if e.type == "tool.invoked"]
    tool_results = [e for e in events if e.type == "tool.result"]
    failures = [e for e in tool_results if not _payload(e).get("success", True)]

    success = result == task.expected_output

    # classify failure from preexisting event data
    if success:
        category = "none"
    elif not tool_invocations:
        category = "no_tools_invoked"
    elif not failures:
        category = "orchestration: no failures recorded"
    else:
        failure_tools = [_payload(e).get("tool_name") or _payload(e).get("tool", "") for e in failures]
        if any("timeout" in str(_payload(e).get("error", "")) for e in failures):
            category = "fault_injection:timeout"
        elif any("malformed" in str(_payload(e).get("error", "")) for e in failures):
            category = "fault_injection:malformed"
        elif all(t == "write_file" for t in failure_tools):
            category = "tool_layer:write_file"
        elif all(t == "list_directory" for t in failure_tools):
            category = "tool_layer:list_directory"
        elif all(t == "read_file" for t in failure_tools):
            category = "tool_layer:read_file"
        else:
            category = f"orchestration: mixed failures {failure_tools}"

    # print tool sequence
    seq = []
    for e in tool_results:
        p = _payload(e)
        name = p.get("tool_name") or p.get("tool", "?")
        ok = p.get("success", False)
        seq.append(f"{'[OK]' if ok else '[FAIL]'}{name}")

    return {
        "success": success,
        "result": str(result),
        "expected": task.expected_output,
        "tool_seq": " -> ".join(seq),
        "category": category,
    }


print("=" * 80)
print("PER-TASK DIAGNOSTICS (using preexisting harness)")
print("=" * 80)

results = []
for task in TASKS:
    d = diagnose(task)
    results.append(d)
    status = "PASS" if d["success"] else "FAIL"
    print(f"\n{status} {task.name}")
    print(f"  result={repr(d['result'])} expected={repr(d['expected'])}")
    print(f"  tools={d['tool_seq']}")
    if not d["success"]:
        print(f"  category={d['category']}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

passed = sum(1 for r in results if r["success"])
failed = [r for r in results if not r["success"]]
print(f"Passed: {passed}/{len(results)}")
print(f"Failed: {len(failed)}")

if failed:
    print("\nFailure breakdown:")
    cats = {}
    for r in failed:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")

    print("\nCornerstone missing capability:")
    top = max(cats.items(), key=lambda x: x[1])
    print(f"  {top[0]} ({top[1]} failures)")
