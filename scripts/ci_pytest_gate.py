"""Judge a pytest JUnit XML report against the explicitly allowed known environment failures.

Mirrors scripts/baseline_gate.ps1: any failure or error NOT in KNOWN_ENV_FAILURES fails the gate. Known failures are
reported individually (still failing / now passing) instead of being hidden. The test count is reported, not pinned,
so the suite may grow; an empty run fails.

Usage: python scripts/ci_pytest_gate.py REPORT.xml [--summary FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

KNOWN_ENV_FAILURES = {
    "tests/test_run_command.py::test_run_command_timeout",
    "tests/test_run_command.py::test_run_command_workspace_cwd",
}


def node_id(case: ET.Element, root: Path) -> str:
    """pytest node id from a JUnit testcase: the longest dotted classname prefix that is an existing .py file becomes
    the path; the remaining parts are classes (e.g. tests.test_x.TestC -> tests/test_x.py::TestC::name)."""
    module = [part for part in case.get("classname", "").split(".") if part]
    name = case.get("name", "")
    for i in range(len(module), 0, -1):
        candidate = "/".join(module[:i]) + ".py"
        if (root / candidate).is_file():
            return "::".join([candidate, *module[i:], name])
    return "::".join([*module, name]) if module else name


def judge(report: Path, root: Path | None = None) -> dict:
    root = root or Path.cwd()
    cases = ET.parse(report).getroot().iter("testcase")
    summary = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "unexpected_failures": [], "known_env_failures_failing": [], "known_env_failures_passing": []}
    seen_known: set[str] = set()
    for case in cases:
        nid = node_id(case, root)
        if case.find("failure") is not None or case.find("error") is not None:
            summary["failed" if case.find("failure") is not None else "errors"] += 1
            if nid in KNOWN_ENV_FAILURES:
                summary["known_env_failures_failing"].append(nid)
                seen_known.add(nid)
            else:
                summary["unexpected_failures"].append(nid)
        elif case.find("skipped") is not None:
            summary["skipped"] += 1
        else:
            summary["passed"] += 1
            if nid in KNOWN_ENV_FAILURES:
                summary["known_env_failures_passing"].append(nid)
                seen_known.add(nid)
    summary["known_env_failures_not_run"] = sorted(KNOWN_ENV_FAILURES - seen_known)
    summary["total"] = summary["passed"] + summary["failed"] + summary["errors"] + summary["skipped"]
    summary["ok"] = summary["total"] > 0 and not summary["unexpected_failures"]
    return summary


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    summary = judge(args.report, args.root)
    print(json.dumps(summary, indent=1))
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if summary["total"] == 0:
        print("PYTEST GATE FAIL: no tests ran")
    elif summary["unexpected_failures"]:
        print("PYTEST GATE FAIL: unexpected failures:\n" + "\n".join(summary["unexpected_failures"]))
    else:
        print(f"PYTEST GATE OK: {summary['passed']} passed, {summary['skipped']} skipped, known environment failures still failing: {len(summary['known_env_failures_failing'])}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
