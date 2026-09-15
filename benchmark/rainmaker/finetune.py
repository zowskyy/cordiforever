from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FineTuneJob:
    job_id: str
    model_base: str
    training_file: str
    output_dir: str
    lora_rank: int = 8
    learning_rate: float = 2e-4
    epochs: int = 3
    batch_size: int = 4
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


class FineTuneTrigger:
    def __init__(self, output_dir: str = "benchmark_results/finetune") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: List[FineTuneJob] = []

    def trigger(self, training_file: str, model_base: str = "qwen2.5-coder:1.5b", **kwargs: Any) -> FineTuneJob:
        job_id = f"finetune_{int(time.time())}"
        job = FineTuneJob(
            job_id=job_id,
            model_base=model_base,
            training_file=training_file,
            output_dir=str(self.output_dir / job_id),
            **kwargs
        )
        self._jobs.append(job)
        self._write_job(job)
        return job

    def generate_config(self, job: FineTuneJob) -> Dict[str, Any]:
        return {
            "job_id": job.job_id,
            "model_base": job.model_base,
            "training_file": job.training_file,
            "output_dir": job.output_dir,
            "lora_config": {
                "r": job.lora_rank,
                "lora_alpha": job.lora_rank * 2,
                "target_modules": ["q_proj", "v_proj"],
                "lora_dropout": 0.05,
            },
            "training_args": {
                "per_device_train_batch_size": job.batch_size,
                "gradient_accumulation_steps": 4,
                "num_train_epochs": job.epochs,
                "learning_rate": job.learning_rate,
                "fp16": True,
                "logging_steps": 10,
                "save_strategy": "epoch",
            },
        }

    def list_jobs(self) -> List[FineTuneJob]:
        return list(self._jobs)

    def _write_job(self, job: FineTuneJob) -> None:
        path = self.output_dir / f"{job.job_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.generate_config(job), f, indent=2)
