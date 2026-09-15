"""Write CI provenance (never part of an experimental result): commit, branch, run, runner, Python, dependency
identity, commands, and hashes of the harness/corpus/gate/scorer sources.

Usage: python scripts/ci_provenance.py OUT.json [--command NAME=CMD ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha256_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def source_hashes() -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    try:
        from benchmark import repo_task_eval as rte  # noqa: PLC0415 - optional: harness hash as the evaluator defines it

        hashes["harness_sha256"] = rte.harness_hash()
        hashes["corpus_sha256"] = rte.corpus_hash()
    except Exception as exc:  # recorded, not hidden: provenance must still be written
        hashes["harness_hash_error"] = f"{type(exc).__name__}: {exc}"
    hashes["frozen_manifest_sha256"] = sha256_file(ROOT / "benchmark" / "FROZEN_MANIFEST.json")
    hashes["research_yield_sha256"] = sha256_file(ROOT / "RESEARCH_YIELD.md")
    for path in sorted((ROOT / "benchmark" / "gates").glob("*.md")) + sorted((ROOT / "benchmark" / "scoring").glob("*.py")):
        hashes[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    return hashes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--command", action="append", default=[], help="NAME=COMMAND recorded verbatim")
    args = parser.parse_args(argv)
    env = os.environ
    provenance = {
        "purpose": "CI verification provenance; not an experimental result",
        "commit_sha": env.get("GITHUB_SHA"),
        "ref": env.get("GITHUB_REF"),
        "branch": env.get("GITHUB_REF_NAME"),
        "event": env.get("GITHUB_EVENT_NAME"),
        "workflow_run_id": env.get("GITHUB_RUN_ID"),
        "workflow_run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "job": env.get("GITHUB_JOB"),
        "runner_os": env.get("RUNNER_OS"),
        "runner_image": env.get("ImageOS"),
        "runner_image_version": env.get("ImageVersion"),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "dependency_definition": {"path": "requirements.txt", "sha256": sha256_file(ROOT / "requirements.txt")},
        "commands": dict(item.split("=", 1) for item in args.command if "=" in item),
        "sources": source_hashes(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(provenance, indent=1), encoding="utf-8")
    print(json.dumps({k: provenance[k] for k in ("commit_sha", "branch", "workflow_run_id", "runner_os", "python_version")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
