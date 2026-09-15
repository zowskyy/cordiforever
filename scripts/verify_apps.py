#!/usr/bin/env python3
"""Run all AppVerifier checks on a workspace and produce structured reports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.context import Context
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.agent.app_verifier import AppVerifier, GateResult, VerificationCriterion
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools


def _build_verifier(workspace: Path) -> AppVerifier:
    ctx = Context(config={"workspace": str(workspace), "profile": "lite"})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(workspace / "test_audit.db"))
    reg.register(FileTools(workspace))
    verifier = AppVerifier()
    verifier.register(ctx)
    reg.start_all()
    return verifier


def _default_criteria(verifier: AppVerifier, user_request: str) -> list[VerificationCriterion]:
    task_state: dict[str, Any] = {}
    return verifier.define_criteria(user_request, task_state)


def run_verification(workspace: Path, user_request: str = "verify app completion") -> dict[str, Any]:
    verifier = _build_verifier(workspace)
    try:
        criteria = _default_criteria(verifier, user_request)
        passed = verifier.verify_completion(str(workspace), {"app_type": "generic"})
        results: list[dict[str, Any]] = []
        for criterion, result in zip(criteria, verifier._results):
            results.append({
                "name": criterion.name,
                "check_type": criterion.check_type,
                "required": criterion.required,
                "passed": result.passed,
                "evidence": result.evidence,
                "feedback": result.feedback,
            })
        return {
            "workspace": str(workspace),
            "user_request": user_request,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "passed": passed,
            "criteria_count": len(criteria),
            "failed_count": sum(1 for r in results if not r["passed"]),
            "results": results,
            "feedback": verifier.get_feedback(),
        }
    finally:
        verifier.stop()


def write_json_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "verification_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report_path


def write_markdown_report(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "verification_report.md"
    lines = [
        f"# App Verification Report",
        f"",
        f"- **Workspace:** {report['workspace']}",
        f"- **Request:** {report['user_request']}",
        f"- **Timestamp:** {report['timestamp']}",
        f"- **Overall:** {'PASSED' if report['passed'] else 'FAILED'}",
        f"- **Criteria:** {report['criteria_count']} total, {report['failed_count']} failed",
        f"",
        f"## Results",
        f"",
        f"| Name | Type | Required | Passed | Feedback |",
        f"|------|------|----------|--------|----------|",
    ]
    for r in report["results"]:
        status = "PASS" if r["passed"] else "FAIL"
        feedback = (r["feedback"] or "").replace("|", "/")
        lines.append(f"| {r['name']} | {r['check_type']} | {r['required']} | {status} | {feedback} |")
    lines.append("")
    lines.append("## Feedback")
    lines.append("")
    lines.append(report.get("feedback", ""))
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AppVerifier checks on a workspace.")
    parser.add_argument("workspace", type=Path, help="Workspace directory to verify")
    parser.add_argument("--output-dir", type=Path, default=Path("audit_reports"), help="Output directory for reports")
    parser.add_argument("--format", choices=["json", "markdown", "both"], default="both", help="Output format")
    parser.add_argument("--request", default="verify app completion", help="User request to derive criteria from")
    args = parser.parse_args()

    if not args.workspace.is_dir():
        print(f"Error: workspace is not a directory: {args.workspace}", file=sys.stderr)
        return 1

    report = run_verification(args.workspace, args.request)
    output_paths = []
    if args.format in ("json", "both"):
        output_paths.append(write_json_report(report, args.output_dir))
    if args.format in ("markdown", "both"):
        output_paths.append(write_markdown_report(report, args.output_dir))

    for path in output_paths:
        print(f"Report written: {path}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
