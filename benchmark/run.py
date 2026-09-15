#!/usr/bin/env python
"""
Run benchmark tasks and record results
"""

import argparse
import json
import sys
import os
import tempfile
import shutil
import tracemalloc
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from benchmark.tasks.long_horizon import get_all_tasks, get_tasks_by_tag
from benchmark.tasks import integration, swe_style, exact_ops  # noqa: F401 - registers task modules
from benchmark.tasks.verification import TaskVerifier, VerifiedBenchmarkTask
from benchmark.report import BenchmarkAnalyzer, TrajectoryMetrics, StepMetrics

from core.context import Context
from core.messages import Message
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools


class DeterministicModel(Plugin):
    name = "ollama_model"
    dependencies = ()

    def __init__(self, task):
        super().__init__()
        self.task = task
        self.call_count = 0

    def chat(self, messages, tools):
        self.call_count += 1
        if self.task.model_responses:
            idx = min(self.call_count - 1, len(self.task.model_responses) - 1)
            return self.task.model_responses[idx]
        return Message("assistant", "done")

    def start(self):
        pass

    def stop(self):
        pass


def _tag_failure_mode(task, success: bool, steps: list) -> Optional[str]:
    if success:
        return None
    if "token_sensitive" in task.tags or "exact" in task.tags:
        return "token_sensitive"
    if "cross_file" in task.tags:
        return "cross_file"
    if "recovery" in task.tags:
        return "lifecycle"
    if any(not s.success for s in steps):
        return "tool_failure"
    return "open_ended"


class BenchmarkRunner:
    def __init__(self, model: str, max_steps: int = 100, real_model: bool = False):
        self.model = model
        self.max_steps = max_steps
        self.real_model = real_model
        self.analyzer = BenchmarkAnalyzer()
        self.results = []
        if real_model and model == "phi3:mini":
            print("[benchmark] Warning: phi3:mini has limited tool-use capability. Prefer qwen2.5-coder:1.5b or qwen3:8b for real-model runs.")

    def run_task(self, task) -> TrajectoryMetrics:
        workspace = task.setup_fn()
        try:
            trajectory = self._run_agent(task, workspace)
            return trajectory
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _run_agent(self, task, workspace) -> TrajectoryMetrics:
        ctx = Context()
        reg = PluginRegistry(ctx)
        db_path = Path(workspace) / "benchmark.db"
        reg.register(EventLogger(db_path))

        if self.real_model:
            real_model = OllamaModel(model=self.model)
            reg.register(real_model)
        else:
            fake_model = DeterministicModel(task)
            reg.register(fake_model)

        reg.register(FileTools(Path(workspace)))
        loop = AgentLoop(max_rounds=self.max_steps)
        reg.register(loop)
        reg.start_all()

        steps = []
        success = False
        partial_credit = 0.0
        tool_call_count = 0
        recovered = 0
        cascade_rate = 0.0
        peak_memory_kb = 0
        result = None
        agent_trace = {"steps": [], "summary": {}}
        verification_result = None

        try:
            tracemalloc.start()
            result = ctx.plugins["agent_loop"].run(task.user_input)
            agent_trace["result"] = result
            _, peak = tracemalloc.get_traced_memory()
            peak_memory_kb = int(peak / 1024)
            tracemalloc.stop()

            el = ctx.plugins["event_logger"]
            cont = el.continuity
            session_id = cont.session_id if hasattr(cont, "session_id") else "default"
            events = el.event_log.get_session_events(session_id)
            invocations = [e for e in events if e.type == "tool.invoked"]
            results = [e for e in events if e.type == "tool.result"]
            tool_call_count = len(invocations)

            for i, ev in enumerate(invocations):
                result_ev = next((r for r in results if r.payload.get("call_id") == ev.payload.get("call_id")), None)
                payload = result_ev.payload if result_ev else {}
                step = {
                    "step_id": i,
                    "tool_name": ev.payload.get("tool_name", "unknown"),
                    "success": payload.get("success", False),
                    "recovery": False,
                    "arguments": ev.payload.get("arguments", {}),
                }
                agent_trace["steps"].append(step)
                steps.append(StepMetrics(
                    step_id=i,
                    tool_name=ev.payload.get("tool_name", "unknown"),
                    success=payload.get("success", False),
                    duration_ms=100.0 + i * 10,
                    token_cost=50 + i * 5,
                    error_type=payload.get("error_type"),
                    recovery_attempts=0,
                    is_recovery_step=False,
                    dependency_ids=[i-1] if i > 0 else []
                ))

            if isinstance(task, VerifiedBenchmarkTask) and task.verification:
                verifier = TaskVerifier()
                workspace_path = Path(workspace)
                verification_result = verifier.verify(task, agent_trace, workspace_path)
                success = verification_result["legitimate_success"]
            else:
                success = result == task.expected_output

            if task.partial_credit_fn:
                partial_credit = task.partial_credit_fn(workspace)
            elif success:
                partial_credit = 1.0

            failed = [s for s in steps if not s.success]
            recovered = 0
            for i, s in enumerate(steps):
                if not s.success:
                    for j in range(i+1, len(steps)):
                        if steps[j].success:
                            recovered += 1
                            break
            recovery_rate = recovered / max(len(failed), 1) if failed else 1.0

            loop_count = 0
            sig_counts = {}
            for s in steps:
                key = s.tool_name
                sig_counts[key] = sig_counts.get(key, 0) + 1
                if sig_counts[key] >= 3:
                    loop_count += 1
            loop_rate = loop_count / max(len(steps), 1)

            cascade = 0
            for i, s in enumerate(steps):
                if not s.success:
                    for j in range(i+1, min(i+4, len(steps))):
                        if not steps[j].success:
                            cascade += 1
                            break
            cascade_rate = cascade / max(len([s for s in steps if not s.success]), 1) if any(not s.success for s in steps) else 0.0

        except Exception as exc:
            pass
        finally:
            reg.stop_all()
            ctx.plugins["event_logger"].event_log.close()

        return TrajectoryMetrics(
            trajectory_id=f"{task.name}_{datetime.now().isoformat()}",
            task_name=task.name,
            horizon_length=task.horizon,
            success=success,
            partial_credit=partial_credit,
            total_steps=len(steps),
            total_tokens=sum(s.token_cost for s in steps),
            total_duration_ms=sum(s.duration_ms for s in steps),
            abort_reason=None,
            recovery_count=recovered,
            recovery_latency_avg=0.0,
            cascade_rate=cascade_rate,
            breakage_step=None,
            breakage_tool=None,
            breakage_type=None,
            prevented_failures=0,
            tool_calls_per_success=tool_call_count / max(success and 1 or 1, 1),
            steps=steps,
            peak_memory_kb=peak_memory_kb,
            failure_mode=_tag_failure_mode(task, success, steps),
            verification=verification_result,
        )

    def run_all(self, tags: Optional[List[str]] = None) -> Dict:
        if tags:
            tasks = []
            for tag in tags:
                tasks.extend(get_tasks_by_tag(tag))
        else:
            tasks = get_all_tasks()

        results = []
        for task in tasks:
            user_input = task.user_input or task.description
            if self.real_model and not user_input:
                continue
            task.user_input = user_input
            try:
                trajectory = self.run_task(task)
                self.analyzer.record_trajectory(trajectory)
                results.append(trajectory)
            except Exception as e:
                print(f"Task {task.name} failed: {e}")
                continue

        report = self.analyzer.generate_report()
        return {"report": report, "trajectories": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="phi3:mini", help="Ollama model to use")
    parser.add_argument("--tasks", choices=["all", "stress", "recovery", "folding", "integration"],
                        default="all", help="Task filter")
    parser.add_argument("--output", default="benchmark_results.json", help="Output file path")
    parser.add_argument("--max-steps", type=int, default=100, help="Maximum steps per task")
    parser.add_argument("--db", default="benchmark_results.db", help="SQLite database path")
    parser.add_argument("--real-model", action="store_true", help="Use real Ollama model instead of deterministic responses")

    args = parser.parse_args()
    tag_map = {"all": None, "stress": ["recovery", "folding"], "recovery": ["recovery"], "folding": ["folding"], "integration": ["integration"]}
    tags = tag_map.get(args.tasks)

    runner = BenchmarkRunner(args.model, args.max_steps, real_model=args.real_model)
    runner.analyzer = BenchmarkAnalyzer(args.db)
    results = runner.run_all(tags)

    with open(args.output, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "model": args.model,
            "report": results["report"].to_dict(),
            "trajectories": [t.__dict__ for t in results["trajectories"]]
        }, f, indent=2, default=str)

    report = results["report"]
    print("\n" + "="*50)
    print("BENCHMARK RESULTS")
    print("="*50)
    print(f"Success Rate: {report.success_rate:.1%}")
    print(f"Partial Credit Avg: {report.partial_credit_avg:.1%}")
    print(f"Cascade Rate: {report.cascade_rate:.1%}")
    print(f"Recovery Efficiency: {report.recovery_efficiency:.1%}")
    print(f"Total Trajectories: {report.total_trajectories}")
    print("="*50)
    print(f"\nResults saved to: {args.output}")
    print(f"Database: {args.db}")


if __name__ == "__main__":
    main()
