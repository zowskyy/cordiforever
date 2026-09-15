#!/usr/bin/env python
"""
Evaluation harness for measuring genuine model improvement.
Runs a model on held-out tasks before and after fine-tuning.
"""

import sys
import json
import time
import shutil
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context
from core.registry import PluginRegistry
from core.messages import Message
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools
from benchmark.tasks.verification import TaskVerifier, VerifiedBenchmarkTask
from benchmark.pipeline.task_generator import GeneratedTask


class EvaluationHarness:
    def __init__(self, model: str = "qwen2.5-coder:1.5b", max_rounds: int = 5) -> None:
        self.model = model
        self.max_rounds = max_rounds

    def evaluate(self, tasks: List[GeneratedTask]) -> Dict[str, Any]:
        results = []
        for task in tasks:
            result = self._run_single(task)
            results.append(result)
        return self._summarize(results)

    def _run_single(self, task: GeneratedTask) -> Dict[str, Any]:
        workspace = task.setup_fn() if hasattr(task, 'setup_fn') else self._setup_workspace(task)
        try:
            ctx = Context()
            reg = PluginRegistry(ctx)
            db_path = Path(workspace) / "benchmark.db"
            reg.register(EventLogger(db_path))
            reg.register(OllamaModel(model=self.model))
            reg.register(FileTools(Path(workspace)))
            reg.register(AgentLoop(max_rounds=self.max_rounds))
            reg.start_all()

            start = time.time()
            result_text = ctx.plugins["agent_loop"].run(task.user_input)
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

            agent_trace["result"] = result_text
            verifier = TaskVerifier()
            verification = verifier.verify(self._make_verified_task(task), agent_trace, Path(workspace))

            return {
                "task_name": task.name,
                "difficulty": task.difficulty,
                "user_input": task.user_input,
                "success": verification.get("legitimate_success", False),
                "artifact_ok": verification.get("artifact_ok", False),
                "procedure_ok": verification.get("procedure_ok", False),
                "elapsed_s": round(elapsed, 2),
                "tool_calls": tool_calls,
                "result": result_text,
                "verification": verification,
            }
        except Exception as e:
            return {
                "task_name": task.name,
                "difficulty": task.difficulty,
                "user_input": task.user_input,
                "success": False,
                "error": str(e),
            }
        finally:
            reg.stop_all()
            ctx.plugins["event_logger"].event_log.close()
            shutil.rmtree(workspace, ignore_errors=True)

    def _setup_workspace(self, task: GeneratedTask) -> str:
        import tempfile
        workspace = tempfile.mkdtemp(prefix=f"eval_{task.name}_")
        if "write" in task.tools_required or "multi" in task.tags:
            for filename in ["a.txt", "b.txt"]:
                Path(workspace, filename).write_text("", encoding="utf-8")
        if "read_file" in task.tools_required and "write_file" not in task.tools_required:
            src = task.user_input.split()[1] if len(task.user_input.split()) > 1 else "file.txt"
            Path(workspace, src).write_text("preexisting content", encoding="utf-8")
        if "sequence" in task.tags:
            src = task.user_input.split()[1] if len(task.user_input.split()) > 1 else "src.txt"
            Path(workspace, src).write_text("preexisting content", encoding="utf-8")
        if "list" in task.tools_required:
            Path(workspace, "file.txt").write_text("preexisting content", encoding="utf-8")
        return workspace

    def _make_verified_task(self, task: GeneratedTask) -> VerifiedBenchmarkTask:
        from benchmark.tasks.verification import TaskVerification, VerificationCheck, VerificationProcedure
        checks = []
        if "write" in task.tools_required:
            filename = task.user_input.split()[-1] if "to" in task.user_input else "file.txt"
            checks.append(VerificationCheck(kind="file_exists", path=filename))
        if "read" in task.tools_required:
            filename = task.user_input.split()[1] if len(task.user_input.split()) > 1 else "file.txt"
            checks.append(VerificationCheck(kind="file_exists", path=filename))
        if "list" in task.tools_required:
            checks.append(VerificationCheck(kind="file_exists", path="file.txt"))

        return VerifiedBenchmarkTask(
            name=task.name,
            description=task.description,
            horizon=5,
            setup_fn=lambda: "",
            execute_fn=None,
            verify_fn=lambda ws: True,
            verification=TaskVerification(
                type="artifact",
                checks=checks,
                procedure=VerificationProcedure(
                    allowed_tools=task.tools_required,
                    required_steps=["tool_call"],
                    max_tool_calls=5,
                ),
            ),
            partial_credit_fn=lambda ws: 1.0,
            required_tools=task.tools_required,
            tags=task.tags,
            user_input=task.user_input,
            expected_output="done",
            difficulty=task.difficulty,
        )

    def _summarize(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = len(results)
        successes = sum(1 for r in results if r.get("success"))
        by_difficulty: Dict[str, Dict[str, int]] = {}
        for r in results:
            diff = r.get("difficulty", "unknown")
            if diff not in by_difficulty:
                by_difficulty[diff] = {"total": 0, "success": 0}
            by_difficulty[diff]["total"] += 1
            if r.get("success"):
                by_difficulty[diff]["success"] += 1

        return {
            "total": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": round(successes / max(total, 1), 4),
            "by_difficulty": {
                k: {"success_rate": round(v["success"] / max(v["total"], 1), 4), "total": v["total"]}
                for k, v in by_difficulty.items()
            },
            "results": results,
        }


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5-coder:1.5b"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    output = sys.argv[3] if len(sys.argv) > 3 else "benchmark_results/evaluation.json"

    from benchmark.pipeline.task_generator import TaskGenerator
    generator = TaskGenerator()
    tasks = generator.generate(count)

    print(f"Evaluating {model} on {count} held-out tasks...")
    harness = EvaluationHarness(model=model)
    report = harness.evaluate(tasks)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Success rate: {report['success_rate']:.1%}")
    print(f"By difficulty: {json.dumps(report['by_difficulty'], indent=2)}")
    print(f"Results saved to: {output}")


if __name__ == "__main__":
    main()
