import json
import tempfile
from pathlib import Path
from core.context import Context
from core.registry import PluginRegistry
from core.messages import Message
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from tests.failure_recovery.harness import DeterministicSandbox, FaultInjectingModel, FaultInjectingTools, Task


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


for task in TASKS:
    tmp = Path(tempfile.mkdtemp())
    sb = DeterministicSandbox(seed=42, tmp_path=tmp)
    sc = sb.run_task(task, "retry")
    print(f"{task.name}: success={sc.task_success} steps={sc.steps_used} error={sc.error}")
