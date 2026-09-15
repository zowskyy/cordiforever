from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.pipeline.task_generator import GeneratedTask, TaskGenerator
from benchmark.pipeline.synthesizer import Synthesizer, Trajectory
from benchmark.rainmaker.feedback import FeedbackStore, TrajectoryRecord
from benchmark.rainmaker.crawler import GitHubCrawler, GitHubTask
from benchmark.rainmaker.finetune import FineTuneTrigger


@dataclass
class RainmakerStats:
    cycles: int = 0
    total_tasks: int = 0
    total_successes: int = 0
    total_failures: int = 0
    overall_success_rate: float = 0.0
    last_cycle_success_rate: float = 0.0
    fine_tune_jobs: int = 0
    start_time: float = field(default_factory=time.time)


class RainmakerLoop:
    def __init__(
        self,
        model: str = "qwen2.5-coder:1.5b",
        max_rounds: int = 5,
        tasks_per_cycle: int = 20,
        fine_tune_threshold: int = 50,
        storage_path: str = "benchmark_results/rainmaker",
        use_github: bool = False,
        github_repos: Optional[List[str]] = None,
    ) -> None:
        self.model = model
        self.max_rounds = max_rounds
        self.tasks_per_cycle = tasks_per_cycle
        self.fine_tune_threshold = fine_tune_threshold
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.generator = TaskGenerator()
        self.synthesizer = Synthesizer(model=model, max_rounds=max_rounds)
        self.feedback = FeedbackStore(storage_path=str(self.storage_path / "feedback"))
        self.finetune = FineTuneTrigger(output_dir=str(self.storage_path / "finetune"))
        self.crawler = GitHubCrawler() if use_github else None
        self.github_repos = github_repos or []

        self.stats = RainmakerStats()

    def run_cycle(self) -> Dict[str, Any]:
        self.stats.cycles += 1
        cycle_start = time.time()

        tasks = self._get_tasks()
        trajectories = self._synthesize_tasks(tasks)
        self._store_trajectories(trajectories)
        cycle_stats = self._compute_stats(trajectories)

        successful_count = sum(1 for t in trajectories if t.success)
        cumulative_successes = self.feedback.success_rate() * len(self.feedback._records)
        if cumulative_successes >= self.fine_tune_threshold:
            self._trigger_fine_tune()

        self.stats.total_tasks += len(trajectories)
        self.stats.total_successes += successful_count
        self.stats.total_failures += len(trajectories) - successful_count
        self.stats.overall_success_rate = self.stats.total_successes / max(self.stats.total_tasks, 1)
        self.stats.last_cycle_success_rate = successful_count / max(len(trajectories), 1)

        cycle_report = {
            "cycle": self.stats.cycles,
            "tasks_attempted": len(trajectories),
            "tasks_succeeded": successful_count,
            "tasks_failed": len(trajectories) - successful_count,
            "cycle_success_rate": self.stats.last_cycle_success_rate,
            "overall_success_rate": self.stats.overall_success_rate,
            "elapsed_s": round(time.time() - cycle_start, 2),
            "fine_tune_jobs": self.stats.fine_tune_jobs,
        }

        report_path = self.storage_path / f"cycle_{self.stats.cycles:04d}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(cycle_report, f, indent=2)

        return cycle_report

    def run_n_cycles(self, n: int) -> List[Dict[str, Any]]:
        reports = []
        for i in range(n):
            report = self.run_cycle()
            reports.append(report)
            print(f"Cycle {i+1}/{n}: {report['cycle_success_rate']:.1%} success rate")
        return reports

    def export_training_data(self, output_path: str, difficulty: Optional[str] = None) -> int:
        return self.feedback.export_training_set(output_path, min_difficulty=difficulty)

    def _get_tasks(self) -> List[Any]:
        if self.crawler and self.github_repos:
            return self._get_github_tasks()
        return self.generator.generate(self.tasks_per_cycle)

    def _get_github_tasks(self) -> List[Any]:
        all_tasks = []
        for repo in self.github_repos:
            issues = self.crawler.fetch_tasks([repo], max_per_repo=self.tasks_per_cycle)
            all_tasks.extend(issues)
        if not all_tasks:
            return self.generator.generate(self.tasks_per_cycle)
        return all_tasks[:self.tasks_per_cycle]

    def _synthesize_tasks(self, tasks: List[Any]) -> List[Trajectory]:
        trajectories = []
        for task in tasks:
            if isinstance(task, GitHubTask):
                task = task.to_generated_task()
            trajectory = self.synthesizer.synthesize(task)
            trajectories.append(trajectory)
        return trajectories

    def _store_trajectories(self, trajectories: List[Trajectory]) -> None:
        import time
        for traj in trajectories:
            source = "github" if "github" in traj.task.tags else "synthetic"
            record = TrajectoryRecord(
                trajectory_id=f"{int(time.time()*1000)}_{self.stats.cycles}_{traj.task.name}",
                task_name=traj.task.name,
                difficulty=traj.task.difficulty,
                tags=traj.task.tags,
                user_input=traj.task.user_input,
                conversation=traj.conversation,
                result=traj.result,
                success=traj.success,
                verification=traj.verification,
                model=self.model,
                elapsed_s=0.0,
                source=source,
            )
            self.feedback.add(record)

    def _trigger_fine_tune(self) -> None:
        export_path = str(self.storage_path / "training_data.jsonl")
        count = self.feedback.export_training_set(export_path)
        if count == 0:
            return
        job = self.finetune.trigger(
            training_file=export_path,
            model_base=self.model,
            epochs=3,
            batch_size=4,
        )
        self.stats.fine_tune_jobs += 1

    def _compute_stats(self, trajectories: List[Trajectory]) -> Dict[str, Any]:
        by_difficulty: Dict[str, Dict[str, int]] = {}
        for traj in trajectories:
            diff = traj.task.difficulty
            if diff not in by_difficulty:
                by_difficulty[diff] = {"total": 0, "success": 0}
            by_difficulty[diff]["total"] += 1
            if traj.success:
                by_difficulty[diff]["success"] += 1
        return {
            "by_difficulty": {
                k: {"success_rate": v["success"] / max(v["total"], 1), "total": v["total"]}
                for k, v in by_difficulty.items()
            }
        }
