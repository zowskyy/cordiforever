#!/usr/bin/env python
"""
Rainmaker: automated training loop for SLM tool-use trajectories.
Generates, synthesizes, verifies, and fine-tunes in a continuous cycle.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmark.rainmaker.loop import RainmakerLoop


def main():
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    tasks_per_cycle = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    model = sys.argv[3] if len(sys.argv) > 3 else "qwen2.5-coder:1.5b"
    use_github = "--github" in sys.argv
    github_repos = [
        "microsoft/vscode",
        "facebook/react",
        "python/cpython",
    ]

    print(f"Starting Rainmaker: {cycles} cycles, {tasks_per_cycle} tasks/cycle, model={model}")
    if use_github:
        print(f"GitHub mode: crawling {github_repos}")

    rainmaker = RainmakerLoop(
        model=model,
        tasks_per_cycle=tasks_per_cycle,
        fine_tune_threshold=50,
        use_github=use_github,
        github_repos=github_repos,
    )

    reports = rainmaker.run_n_cycles(cycles)

    print("\n=== RAINMAKER COMPLETE ===")
    print(f"Total cycles: {cycles}")
    print(f"Overall success rate: {reports[-1]['overall_success_rate']:.1%}")
    print(f"Last cycle success rate: {reports[-1]['cycle_success_rate']:.1%}")

    # Export training data
    training_path = "benchmark_results/rainmaker_training.jsonl"
    count = rainmaker.export_training_data(training_path)
    print(f"Exported {count} successful trajectories to {training_path}")

    # Print summary
    summary = {
        "cycles": cycles,
        "tasks_per_cycle": tasks_per_cycle,
        "model": model,
        "reports": reports,
        "training_trajectories": count,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
