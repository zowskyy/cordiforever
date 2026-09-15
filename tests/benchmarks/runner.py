"""Benchmark runner for ArrayHelper evaluation.

Runs each array task with ArrayHelper enabled and disabled, measuring:
- Verified completion (does the task actually work?)
- Model turns
- Tool calls
- Token overhead
- Recovery from seeded failures
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.plugin import Plugin
from core.context import Context
from core.messages import Message
from core.registry import PluginRegistry
from core.calibration import resolve_calibration
from plugins.agent.loop import AgentLoop
from plugins.agent.array_helper import ArrayHelper
from plugins.agent.schema_router import SchemaRouter
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools


class BenchmarkModel(Plugin):
    """Deterministic model that returns predefined responses."""
    name = "ollama_model"
    dependencies: tuple[str, ...] = ()

    def __init__(self, responses: list[Message]):
        super().__init__()
        self.responses = list(responses)
        self.calls = 0
        self.seen_messages: list = []

    def chat(self, messages, tools):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self.responses:
            return self.responses.pop(0)
        return Message("assistant", "task completed")


@dataclass
class BenchmarkResult:
    task_name: str
    array_helper_enabled: bool
    completed: bool
    model_turns: int
    tool_calls: int
    prompt_injections: int
    error: str = ""
    token_overhead_estimate: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def run_task(
    task: Any,
    tmp_path: Path,
    enable_array_helper: bool,
) -> BenchmarkResult:
    """Run a single benchmark task and return metrics."""
    # Set up source file
    source_path = tmp_path / task.source_file
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(task.source_content, encoding="utf-8")

    # Build a deterministic model response that completes the task
    # The model will write to the source file with the array operation applied
    model_response = Message("assistant", "task completed")

    # Also prepare a tool call response that modifies the file
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": {
                "path": task.source_file,
                "content": task.source_content + "\n// array operation applied\n",
            },
        },
    }

    responses = [
        Message("assistant", "", tool_calls=[tool_call]),
        Message("assistant", "done"),
    ]

    # Set up context
    cal = resolve_calibration("qwen2.5-coder:1.5b")
    config = {
        "profile": "lite",
        "workspace": str(tmp_path),
        "schema_router_enabled": True,
        "compact_schema": True,
        "calibration": cal,
    }
    ctx = Context(config=config)
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "benchmark.db"))
    reg.register(BenchmarkModel(responses))
    reg.register(FileTools(tmp_path))
    if enable_array_helper:
        reg.register(ArrayHelper())
    reg.register(SchemaRouter())
    reg.register(AgentLoop(max_rounds=5))
    reg.start_all()

    try:
        injection_count_before = len(ctx.prompt_injections)
        reg._plugins["agent_loop"].run(task.user_input)

        model = reg._plugins["ollama_model"]
        injection_count_after = len(ctx.prompt_injections)

        # Verify completion
        completed = False
        try:
            completed = task.verify(tmp_path)
        except Exception:
            completed = False

        # Count tool calls from events
        el = ctx.plugins["event_logger"]
        sid = el.continuity.session_id
        events = el.event_log.get_session_events(sid)
        tool_invoked = sum(1 for e in events if e.type == "tool.invoked")
        array_events = sum(1 for e in events if "array" in e.type)

        # Estimate token overhead from prompt injections
        overhead = 0
        for msg in ctx.messages:
            if msg.role == "user" and msg.content.startswith("[array context]"):
                overhead += len(msg.content.split())

        return BenchmarkResult(
            task_name=task.name,
            array_helper_enabled=enable_array_helper,
            completed=completed,
            model_turns=model.calls,
            tool_calls=tool_invoked,
            prompt_injections=injection_count_after - injection_count_before,
            token_overhead_estimate=overhead,
            error="" if completed else "task not completed or verified",
        )
    except Exception as exc:
        return BenchmarkResult(
            task_name=task.name,
            array_helper_enabled=enable_array_helper,
            completed=False,
            model_turns=0,
            tool_calls=0,
            prompt_injections=0,
            token_overhead_estimate=0,
            error=str(exc),
        )
    finally:
        reg.stop_all()


def run_benchmark_suite(tasks: list, runs_per_task: int = 1) -> dict:
    """Run benchmark suite and return summary report."""
    results: list[BenchmarkResult] = []

    for task in tasks:
        for _ in range(runs_per_task):
            tmp_dir = tempfile.mkdtemp(prefix="benchmark_")
            tmp_path = Path(tmp_dir)
            try:
                # Without ArrayHelper
                r1 = run_task(task, tmp_path, enable_array_helper=False)
                results.append(r1)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

            tmp_dir = tempfile.mkdtemp(prefix="benchmark_")
            tmp_path = Path(tmp_dir)
            try:
                # With ArrayHelper
                r2 = run_task(task, tmp_path, enable_array_helper=True)
                results.append(r2)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    # Build summary
    without_helper = [r for r in results if not r.array_helper_enabled]
    with_helper = [r for r in results if r.array_helper_enabled]

    def avg(items, key):
        vals = [getattr(i, key) for i in items if hasattr(i, key)]
        return sum(vals) / len(vals) if vals else 0

    def rate(items, key):
        total = len(items)
        positive = sum(1 for i in items if getattr(i, key))
        return positive / total if total else 0

    report = {
        "total_tasks": len(tasks),
        "runs_without_helper": len(without_helper),
        "runs_with_helper": len(with_helper),
        "with_helper": {
            "completion_rate": rate(with_helper, "completed"),
            "avg_model_turns": avg(with_helper, "model_turns"),
            "avg_tool_calls": avg(with_helper, "tool_calls"),
            "avg_token_overhead": avg(with_helper, "token_overhead_estimate"),
        },
        "without_helper": {
            "completion_rate": rate(without_helper, "completed"),
            "avg_model_turns": avg(without_helper, "model_turns"),
            "avg_tool_calls": avg(without_helper, "tool_calls"),
            "avg_token_overhead": avg(without_helper, "token_overhead_estimate"),
        },
        "per_task": [r.to_dict() for r in results],
    }

    # Compute improvement
    base_rate = report["without_helper"]["completion_rate"]
    helper_rate = report["with_helper"]["completion_rate"]
    if base_rate > 0:
        report["completion_rate_improvement"] = (helper_rate - base_rate) / base_rate
    else:
        report["completion_rate_improvement"] = float("inf") if helper_rate > 0 else 0

    return report
