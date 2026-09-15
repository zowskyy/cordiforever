from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TrajectoryRecord:
    trajectory_id: str
    task_name: str
    difficulty: str
    tags: List[str]
    user_input: str
    conversation: List[Dict[str, Any]]
    result: str
    success: bool
    verification: Dict[str, Any]
    model: str
    elapsed_s: float
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"


class FeedbackStore:
    def __init__(self, storage_path: str = "benchmark_results/feedback") -> None:
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, TrajectoryRecord] = {}
        self._load()

    def add(self, record: TrajectoryRecord) -> None:
        self._records[record.trajectory_id] = record
        self._persist(record)

    def get_successful(self, difficulty: Optional[str] = None, tags: Optional[List[str]] = None) -> List[TrajectoryRecord]:
        results = [r for r in self._records.values() if r.success]
        if difficulty is not None:
            results = [r for r in results if r.difficulty == difficulty]
        if tags is not None:
            results = [r for r in results if any(t in r.tags for t in tags)]
        return results

    def get_failed(self, difficulty: Optional[str] = None) -> List[TrajectoryRecord]:
        results = [r for r in self._records.values() if not r.success]
        if difficulty is not None:
            results = [r for r in results if r.difficulty == difficulty]
        return results

    def success_rate(self, difficulty: Optional[str] = None) -> float:
        relevant = [r for r in self._records.values() if difficulty is None or r.difficulty == difficulty]
        if not relevant:
            return 0.0
        return sum(1 for r in relevant if r.success) / len(relevant)

    def export_training_set(self, output_path: str, min_difficulty: Optional[str] = None) -> int:
        records = self.get_successful(difficulty=min_difficulty)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(output, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps({
                    "messages": record.conversation,
                    "tools": [],
                    "verification": record.verification,
                    "task_name": record.task_name,
                    "difficulty": record.difficulty,
                }, ensure_ascii=False) + "\n")
                count += 1
        return count

    def _persist(self, record: TrajectoryRecord) -> None:
        path = self.storage_path / f"{record.trajectory_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record.__dict__, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        for path in self.storage_path.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "source" not in data:
                    data["source"] = "unknown"
                self._records[data["trajectory_id"]] = TrajectoryRecord(**data)
            except Exception:
                continue
