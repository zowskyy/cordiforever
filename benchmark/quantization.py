#!/usr/bin/env python
"""
Quantization benchmark: measure tokens/sec vs success rate
for qwen2.5-coder:1.5b at different quantization levels.
"""

import sys
import time
import json
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context
from core.registry import PluginRegistry
from core.messages import Message
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools
from benchmark.tasks.integration import TaskRegistry
from benchmark.tasks.verification import TaskVerifier, VerifiedBenchmarkTask


TASKS = [
    ("simple_write", "write hello to a.txt"),
    ("simple_read", "read a.txt"),
    ("multi_tool_integration", "create a.txt and b.txt"),
    ("list_directory_integration", "list files"),
]


def run_single(model_name: str, task_name: str, user_input: str) -> dict:
    task = None
    for t in TaskRegistry.get_all():
        if t.name == task_name:
            task = t
            break
    if task is None:
        return {"error": f"Task {task_name} not found"}

    workspace = task.setup_fn()
    try:
        ctx = Context()
        reg = PluginRegistry(ctx)
        db_path = Path(workspace) / "benchmark.db"
        reg.register(EventLogger(db_path))
        reg.register(OllamaModel(model=model_name))
        reg.register(FileTools(Path(workspace)))
        reg.register(AgentLoop(max_rounds=3))
        reg.start_all()

        start = time.time()
        result_text = ctx.plugins["agent_loop"].run(user_input)
        elapsed = time.time() - start

        el = ctx.plugins["event_logger"]
        cont = el.continuity
        session_id = cont.session_id if hasattr(cont, "session_id") else "default"
        events = el.event_log.get_session_events(session_id)
        invocations = [e for e in events if e.type == "tool.invoked"]
        tool_calls = len(invocations)

        agent_trace = {"steps": [], "summary": {}}
        for i, ev in enumerate(invocations):
            agent_trace["steps"].append({
                "step_id": i,
                "tool_name": ev.payload.get("tool_name", "unknown"),
                "success": True,
                "recovery": False,
                "arguments": ev.payload.get("arguments", {}),
            })

        verifier = TaskVerifier()
        verification = verifier.verify(task, agent_trace, Path(workspace))

        tokens_estimate = sum(
            len(m.content.split()) + len(str(getattr(m, "tool_calls", None) or "").split())
            for m in ctx.messages
        )
        tokens_per_sec = tokens_estimate / elapsed if elapsed > 0 else 0

        return {
            "task": task_name,
            "model": model_name,
            "elapsed_s": round(elapsed, 2),
            "tokens_estimate": tokens_estimate,
            "tokens_per_sec": round(tokens_per_sec, 2),
            "tool_calls": tool_calls,
            "legitimate_success": verification["legitimate_success"],
            "artifact_ok": verification["artifact_ok"],
            "execution_ok": verification["execution_ok"],
            "procedure_ok": verification["procedure_ok"],
        }
    except Exception as e:
        return {
            "task": task_name,
            "model": model_name,
            "error": str(e),
        }
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()
        shutil.rmtree(workspace, ignore_errors=True)


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5-coder:1.5b"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    results = []
    for task_name, user_input in TASKS:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(run_single, model, task_name, user_input) for _ in range(runs)]
            for future in as_completed(futures):
                results.append(future.result())

    report = {
        "model": model,
        "runs_per_task": runs,
        "total_tasks": len(results),
        "successes": sum(1 for r in results if r.get("legitimate_success")),
        "avg_elapsed_s": round(sum(r.get("elapsed_s", 0) for r in results) / max(len(results), 1), 2),
        "avg_tokens_per_sec": round(sum(r.get("tokens_per_sec", 0) for r in results) / max(len(results), 1), 2),
        "results": results,
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
