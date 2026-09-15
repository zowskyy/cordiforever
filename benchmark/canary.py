#!/usr/bin/env python
"""
Canary benchmark: single-task real-model validation with debug output.
"""

import sys
import time
import json
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context
from core.plugin import Plugin
from core.registry import PluginRegistry
from core.messages import Message
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.model.ensemble import EnsembleModel
from plugins.tools.file import FileTools
from benchmark.tasks.verification import TaskVerifier, VerifiedBenchmarkTask, TaskVerification, VerificationCheck, VerificationProcedure
from benchmark.tasks.integration import TaskRegistry


def run_canary(model_name: str = "qwen2.5-coder:1.5b", task_name: str = "simple_write", use_ensemble: bool = False) -> dict:
    task = None
    for t in TaskRegistry.get_all():
        if t.name == task_name:
            task = t
            break

    if task is None:
        return {"error": f"Task {task_name} not found"}

    if not isinstance(task, VerifiedBenchmarkTask) or not task.verification:
        return {"error": f"Task {task_name} is not a verified task"}

    workspace = task.setup_fn()
    try:
        ctx = Context()
        reg = PluginRegistry(ctx)
        db_path = Path(workspace) / "benchmark.db"
        reg.register(EventLogger(db_path))

        if use_ensemble:
            model_plugin = EnsembleModel(
                models=[
                    {"model": "qwen2.5-coder:1.5b"},
                    {"model": "qwen2.5-coder:1.5b"},
                    {"model": "qwen2.5-coder:1.5b"},
                ],
                strategy="parallel_vote",
                max_workers=3,
                base_url="http://127.0.0.1:11434",
                timeout=120.0,
            )
        else:
            model_plugin = OllamaModel(model=model_name)

        reg.register(model_plugin)
        reg.register(FileTools(Path(workspace)))
        reg.register(AgentLoop(max_rounds=3))
        reg.start_all()

        # Monkey-patch model chat for debug output
        model_plugin = ctx.plugins["ollama_model"]
        original_chat = model_plugin.chat
        def debug_chat(messages, tools):
            print(f"\n=== Model call ===")
            print(f"Messages count: {len(messages)}")
            for i, m in enumerate(messages[-3:]):
                print(f"  [{i}] role={m.role}, content={repr(m.content[:100])}, tool_calls={m.tool_calls}")
            print(f"Tools count: {len(tools)}")
            resp = original_chat(messages, tools)
            print(f"Response: content={repr(resp.content[:200])}, tool_calls={resp.tool_calls}")
            return resp
        model_plugin.chat = debug_chat

        start = time.time()
        result_text = ctx.plugins["agent_loop"].run(task.user_input)
        elapsed = time.time() - start

        el = ctx.plugins["event_logger"]
        cont = el.continuity
        session_id = cont.session_id if hasattr(cont, "session_id") else "default"
        events = el.event_log.get_session_events(session_id)
        invocations = [e for e in events if e.type == "tool.invoked"]
        results = [e for e in events if e.type == "tool.result"]

        agent_trace = {"steps": [], "summary": {}}
        for i, ev in enumerate(invocations):
            result_ev = next((r for r in results if r.payload.get("call_id") == ev.payload.get("call_id")), None)
            payload = result_ev.payload if result_ev else {}
            agent_trace["steps"].append({
                "step_id": i,
                "tool_name": ev.payload.get("tool_name", "unknown"),
                "success": payload.get("success", False),
                "recovery": False,
                "arguments": ev.payload.get("arguments", {}),
            })

        verifier = TaskVerifier()
        verification = verifier.verify(task, agent_trace, Path(workspace))

        return {
            "task": task.name,
            "model": model_name,
            "elapsed_s": round(elapsed, 2),
            "agent_result": result_text,
            "tool_calls": len(invocations),
            "legitimate_success": verification["legitimate_success"],
            "artifact_ok": verification["artifact_ok"],
            "execution_ok": verification["execution_ok"],
            "procedure_ok": verification["procedure_ok"],
            "verification": verification,
        }
    except Exception as e:
        import traceback
        return {
            "task": task_name,
            "model": model_name,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5-coder:1.5b"
    task = sys.argv[2] if len(sys.argv) > 2 else "simple_write"
    use_ensemble = "--ensemble" in sys.argv
    print(json.dumps(run_canary(model, task, use_ensemble=use_ensemble), indent=2))
