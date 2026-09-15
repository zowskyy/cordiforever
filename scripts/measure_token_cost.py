"""
Quick token-cost measurement for simple tasks.
Uses a shared workspace so file operations work across tasks.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context
from core.registry import PluginRegistry
from core.messages import Message
from core.metrics import TokenUsage
from plugins.agent.loop import AgentLoop
from plugins.agent.schema_router import SchemaRouter
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools


class RecordingModel(OllamaModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, tools):
        start = time.time()
        response = super().chat(messages, tools)
        elapsed = time.time() - start
        usage = self.last_token_usage or TokenUsage()
        self.calls.append({
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "prompt_eval_count": usage.prompt_eval_count,
            "eval_count": usage.eval_count,
            "messages_count": len(messages),
            "tools_count": len(tools),
            "elapsed_seconds": elapsed,
        })
        return response


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def measure_task(task_id: str, user_input: str, profile: str = "lite", workspace: Path | None = None, compact_schema: bool = False) -> dict[str, Any]:
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="measure_"))

    ctx = Context(config={
        "workspace": str(workspace),
        "model": "qwen2.5-coder:1.5b",
        "profile": profile,
        "schema_router_enabled": True,
        "compact_schema": compact_schema,
        "calibration": {
            "max_tokens": 32768,
            "pruner_budget": 30000,
            "safety": 0.85,
            "max_messages": 200,
            "rounds_per_file": 1.05,
            "max_tool_result_bytes": 65536,
        }
    })
    reg = PluginRegistry(ctx)
    model = RecordingModel(model="qwen2.5-coder:1.5b")
    files = FileTools(workspace)
    reg.register(EventLogger(workspace / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(SchemaRouter())
    reg.register(AgentLoop(max_rounds=5))
    reg.start_all()

    start = time.time()
    try:
        result = ctx.plugins["agent_loop"].run(user_input)
        success = True
        error = None
    except Exception as e:
        result = str(e)
        success = False
        error = str(e)
    finally:
        reg.stop_all()
    elapsed = time.time() - start

    total_prompt = sum(c["prompt_eval_count"] for c in model.calls)
    total_eval = sum(c["eval_count"] for c in model.calls)
    total_input = sum(c["input_tokens"] for c in model.calls)
    total_output = sum(c["output_tokens"] for c in model.calls)

    system_msgs = [m for m in ctx.messages if m.role == "system"]
    guidance_tokens = sum(estimate_tokens(m.content) for m in system_msgs)

    tool_schema_text = json.dumps(files.schemas())
    tool_schema_tokens = estimate_tokens(tool_schema_text)

    # Measure active schema tokens (compact vs verbose)
    active_schemas = files.schemas()
    if ctx.plugins.get("schema_router"):
        router = ctx.plugins["schema_router"]
        if getattr(router, "enabled", False) and getattr(router, "compact_mode", False):
            active_schemas = router.get_model_tools() or files.schemas()
    active_schema_text = json.dumps(active_schemas)
    active_schema_tokens = estimate_tokens(active_schema_text)
    schema_mode = "compact" if len(active_schemas) == 1 else "verbose"

    tool_result_tokens = sum(
        estimate_tokens(m.content) for m in ctx.messages if m.role == "tool"
    )

    round_count = len(model.calls)

    loop = ctx.plugins.get("agent_loop")
    retry_count = getattr(loop, "_parse_retry_count", 0) if loop else 0
    replan_count = getattr(loop, "_replan_count", 0) if loop else 0

    return {
        "task_id": task_id,
        "profile": profile,
        "schema_mode": schema_mode,
        "active_schema_tokens": active_schema_tokens,
        "user_input": user_input,
        "success": success,
        "error": error,
        "result": str(result)[:100],
        "total_tokens": total_prompt + total_eval,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "prompt_eval_count": total_prompt,
        "eval_count": total_eval,
        "guidance_tokens": guidance_tokens,
        "tool_schema_tokens": tool_schema_tokens,
        "tool_result_tokens": tool_result_tokens,
        "round_count": round_count,
        "tool_call_count": round_count,
        "retry_count": retry_count,
        "replan_count": replan_count,
        "elapsed_seconds": round(elapsed, 3),
        "model_calls": [
            {
                "prompt_eval_count": c["prompt_eval_count"],
                "eval_count": c["eval_count"],
                "messages_count": c["messages_count"],
                "tools_count": c["tools_count"],
                "elapsed_seconds": round(c["elapsed_seconds"], 3),
            }
            for c in model.calls
        ],
    }


def main():
    print("=" * 80)
    print("TOKEN COST MEASUREMENT HARNESS")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)

        # Pre-populate a.txt for read_file task
        (workspace / "a.txt").write_text("hello world", encoding="utf-8")

        results: dict[str, list[dict[str, Any]]] = {"lite": [], "full": []}

        TASKS = [
            ("write_file", "write hello world to a.txt"),
            ("read_file", "read a.txt"),
            ("list_directory", "list files"),
            ("simple_chat", "say hello"),
            ("math_task", "calculate the derivative of x^2 + 3x"),
            ("datetime_task", "what is 3 days from now"),
            ("units_task", "convert 100 km to miles"),
            ("delete_file", "delete b.txt"),
        ]

        for task_id, user_input in TASKS:
            for profile in ["lite", "full"]:
                print(f"\nMeasuring: {task_id} ({profile})...")
                r = measure_task(task_id, user_input, profile, workspace)
                results[profile].append(r)
                print(f"  tokens={r['total_tokens']}, rounds={r['round_count']}, success={r['success']}, time={r['elapsed_seconds']}s")

    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    for profile in ["lite", "full"]:
        rs = results[profile]
        successful = [r for r in rs if r["success"]]
        total_tokens = sum(r["total_tokens"] for r in successful)
        avg_tokens = total_tokens / len(successful) if successful else 0
        total_prompt = sum(r["prompt_eval_count"] for r in successful)
        total_eval = sum(r["eval_count"] for r in successful)
        completion_rate = len(successful) / len(rs) if rs else 0

        print(f"\n{profile.upper()} PROFILE:")
        print(f"  Tasks: {len(rs)}")
        print(f"  Successful: {len(successful)} ({completion_rate:.0%})")
        print(f"  Total tokens (successful): {total_tokens}")
        print(f"  Total prompt tokens: {total_prompt}")
        print(f"  Total eval tokens: {total_eval}")
        print(f"  Avg tokens per task: {avg_tokens:.0f}")

        for r in rs:
            print(f"    {r['task_id']}: {r['total_tokens']} tokens, {r['round_count']} rounds, success={r['success']}")

    # Calculate reduction
    lite_successful = [r for r in results["lite"] if r["success"]]
    full_successful = [r for r in results["full"] if r["success"]]
    lite_avg = sum(r["total_tokens"] for r in lite_successful) / max(1, len(lite_successful))
    full_avg = sum(r["total_tokens"] for r in full_successful) / max(1, len(full_successful))

    print(f"\nTOKEN REDUCTION ANALYSIS:")
    print(f"  Lite avg tokens/task: {lite_avg:.0f}")
    print(f"  Full avg tokens/task: {full_avg:.0f}")
    if full_avg > 0:
        reduction = (full_avg - lite_avg) / full_avg * 100
        print(f"  Lite vs Full reduction: {reduction:.1f}%")
        if reduction >= 80:
            print("  MEETS 80% TARGET: YES")
        else:
            print("  MEETS 80% TARGET: NO")

    # Save detailed results
    out_path = Path(__file__).parent / "measurement_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    main()
