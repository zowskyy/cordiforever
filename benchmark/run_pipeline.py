#!/usr/bin/env python
"""
Synthetic data pipeline runner.
Generates N trajectories, verifies them, and exports to JSONL.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmark.pipeline.dataset import Pipeline


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen2.5-coder:1.5b"
    output = sys.argv[3] if len(sys.argv) > 3 else "benchmark_results/trajectories.jsonl"

    print(f"Generating {count} trajectories with {model}...")
    pipeline = Pipeline(model=model, max_rounds=5, workers=4)
    trajectories = pipeline.run(count)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    pipeline.export_jsonl(trajectories, output)

    report = pipeline.report(trajectories)
    print(json.dumps(report, indent=2))
    print(f"\nExported to: {output}")


if __name__ == "__main__":
    main()
