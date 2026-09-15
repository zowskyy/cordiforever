from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from benchmark.pipeline.task_generator import GeneratedTask, TaskGenerator
from benchmark.pipeline.synthesizer import Synthesizer, Trajectory


class Pipeline:
    def __init__(self, model: str = "qwen2.5-coder:1.5b", max_rounds: int = 5, workers: int = 4) -> None:
        self.model = model
        self.max_rounds = max_rounds
        self.workers = workers
        self.generator = TaskGenerator()
        self.synthesizer = Synthesizer(model=model, max_rounds=max_rounds)

    def run(self, count: int = 100) -> List[Trajectory]:
        tasks = self.generator.generate(count)
        trajectories: List[Trajectory] = []

        for task in tasks:
            trajectory = self.synthesizer.synthesize(task)
            trajectories.append(trajectory)

        return trajectories

    def export_jsonl(self, trajectories: List[Trajectory], output_path: str) -> None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for traj in trajectories:
                f.write(json.dumps(traj.to_dict(), ensure_ascii=False) + "\n")

    def report(self, trajectories: List[Trajectory]) -> Dict[str, Any]:
        total = len(trajectories)
        successes = sum(1 for t in trajectories if t.success)
        by_difficulty: Dict[str, Dict[str, int]] = {}
        for t in trajectories:
            diff = t.task.difficulty
            if diff not in by_difficulty:
                by_difficulty[diff] = {"total": 0, "success": 0}
            by_difficulty[diff]["total"] += 1
            if t.success:
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
        }
