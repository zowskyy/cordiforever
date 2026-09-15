"""Verify frozen experiment evidence without re-running anything.

This script never imports or executes a scorer, gate, evaluator or model. It only reads bytes that are already
committed and checks them against records that are already committed:

  manifest   every file under the frozen evidence trees matches benchmark/FROZEN_MANIFEST.json (sha256), and no
             evidence file is missing from or added to the manifest without an explicit local --write
  logged     for every path that EXPERIMENT_LOG.md records with a full 64-hex sha256, the LAST recorded value
             equals the file's current bytes (earlier values are pre-inspection history, e.g. a superseded scorer)
  scorer     each frozen *_scorer_stdout.txt parses, names a gate and scorer whose current bytes match the sha256
             it recorded, and (when a frozen JSON with a verdict exists) reports the same verdict result
  rows       benchmark/results/repo_task_eval.jsonl rows parse, carry required keys, and have no duplicate
             (condition, split, task, fingerprint)

Usage:
  python scripts/verify_frozen_artifacts.py [--root DIR] [--check manifest|logged|scorer|rows|all] [--report FILE]
  python scripts/verify_frozen_artifacts.py --write-manifest     # LOCAL ONLY: after an intentional evidence change
Exit code 0 when every selected check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

FROZEN_TREES = ("benchmark/gates", "benchmark/scoring", "benchmark/results", "benchmark/oracle", "benchmark/repos")
FROZEN_FILES = ("benchmark/repo_tasks.py",)
MANIFEST = "benchmark/FROZEN_MANIFEST.json"
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
ROW_KEYS = ("condition", "split", "task", "fingerprint")
LOGGED_HASH = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`[^\n`]{0,60}?`([0-9a-f]{64})`")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evidence_files(root: Path) -> list[str]:
    paths: set[str] = set()
    for tree in FROZEN_TREES:
        base = root / tree
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file() and not (SKIP_PARTS & set(path.relative_to(root).parts)) and path.suffix != ".pyc":
                    paths.add(path.relative_to(root).as_posix())
    for name in FROZEN_FILES:
        if (root / name).is_file():
            paths.add(name)
    return sorted(paths)


def build_manifest(root: Path) -> dict[str, str]:
    return {rel: sha256_bytes((root / rel).read_bytes()) for rel in evidence_files(root)}


def check_manifest(root: Path) -> list[str]:
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        return [f"manifest: {MANIFEST} is missing"]
    recorded: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    current = build_manifest(root)
    errors = [f"manifest: {rel} is recorded but missing" for rel in sorted(set(recorded) - set(current))]
    errors += [f"manifest: {rel} exists but is not recorded" for rel in sorted(set(current) - set(recorded))]
    errors += [f"manifest: {rel} sha256 {current[rel][:12]} != recorded {recorded[rel][:12]}"
               for rel in sorted(set(current) & set(recorded)) if current[rel] != recorded[rel]]
    return errors


def last_logged_hashes(log_text: str) -> dict[str, str]:
    logged: dict[str, str] = {}
    for match in LOGGED_HASH.finditer(log_text):
        logged[match.group(1)] = match.group(2)  # later occurrences overwrite earlier ones
    return logged


def check_logged(root: Path) -> tuple[list[str], int]:
    errors: list[str] = []
    checked = 0
    for rel, expected in last_logged_hashes((root / "EXPERIMENT_LOG.md").read_text(encoding="utf-8")).items():
        path = root / rel
        if not path.is_file():
            continue  # historical references to files that were never committed (e.g. scratchpad scripts)
        checked += 1
        actual = sha256_bytes(path.read_bytes())
        if actual != expected:
            errors.append(f"logged: {rel} sha256 {actual[:12]} != last logged {expected[:12]}")
    return errors, checked


def _load_json_text(path: Path) -> Any:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def check_scorer_outputs(root: Path) -> tuple[list[str], int]:
    errors: list[str] = []
    stdouts = sorted((root / "benchmark" / "results").glob("*_scorer_stdout.txt"))
    for stdout in stdouts:
        rel = stdout.relative_to(root).as_posix()
        try:
            data = _load_json_text(stdout)
        except ValueError as exc:
            errors.append(f"scorer: {rel} is not valid JSON ({exc})")
            continue
        for key in ("gate", "scorer"):
            entry = data.get(key) or {}
            target = root / str(entry.get("path", ""))
            if not entry.get("path") or not target.is_file():
                errors.append(f"scorer: {rel} names missing {key} file {entry.get('path')!r}")
            elif sha256_bytes(target.read_bytes()) != entry.get("sha256"):
                errors.append(f"scorer: {rel} recorded {key} sha256 does not match {entry.get('path')}")
        frozen = root / "benchmark" / "results" / stdout.name.replace("_scorer_stdout.txt", "_frozen.json")
        verdict = data.get("verdict") or {}
        if frozen.is_file() and "result" in verdict:
            frozen_verdict = (_load_json_text(frozen).get("verdict") or {})
            if frozen_verdict.get("result") != verdict.get("result"):
                errors.append(f"scorer: {rel} verdict {verdict.get('result')!r} != {frozen.name} {frozen_verdict.get('result')!r}")
        if "result" not in verdict:
            errors.append(f"scorer: {rel} has no verdict result")
    return errors, len(stdouts)


def check_rows(root: Path) -> tuple[list[str], int]:
    path = root / "benchmark" / "results" / "repo_task_eval.jsonl"
    if not path.is_file():
        return [], 0
    errors: list[str] = []
    seen: set[tuple[str, ...]] = set()
    count = 0
    for number, line in enumerate(path.read_bytes().decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        count += 1
        try:
            row = json.loads(line)
        except ValueError:
            errors.append(f"rows: line {number} is not valid JSON")
            continue
        missing = [key for key in ROW_KEYS if not row.get(key)]
        if missing:
            errors.append(f"rows: line {number} missing {', '.join(missing)}")
            continue
        key = tuple(str(row[k]) for k in ROW_KEYS)
        if key in seen:
            errors.append(f"rows: line {number} duplicates {key}")
        seen.add(key)
    return errors, count


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", choices=("manifest", "logged", "scorer", "rows", "all"), default="all")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write_manifest:
        files = build_manifest(root)
        (root / MANIFEST).write_text(json.dumps({"trees": list(FROZEN_TREES) + list(FROZEN_FILES), "files": files}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {MANIFEST} with {len(files)} files")
        return 0
    report: dict[str, Any] = {}
    errors: list[str] = []
    if args.check in ("manifest", "all"):
        found = check_manifest(root)
        report["manifest"] = {"files": len(evidence_files(root)), "errors": found}
        errors += found
    if args.check in ("logged", "all"):
        found, checked = check_logged(root)
        report["logged"] = {"paths_checked": checked, "errors": found}
        errors += found
    if args.check in ("scorer", "all"):
        found, checked = check_scorer_outputs(root)
        report["scorer"] = {"stdout_files_checked": checked, "scorers_executed": 0, "errors": found}
        errors += found
    if args.check in ("rows", "all"):
        found, checked = check_rows(root)
        report["rows"] = {"rows_checked": checked, "errors": found}
        errors += found
    report["ok"] = not errors
    for error in errors:
        print(error)
    print(json.dumps({k: (v if k == "ok" else {kk: vv for kk, vv in v.items() if kk != "errors"}) for k, v in report.items()}, indent=1))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
