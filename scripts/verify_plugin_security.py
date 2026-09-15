#!/usr/bin/env python3
"""Plugin security gate — scan plugins/ for dangerous patterns.

This script is a CI/data-gathering tool only. It does not modify production
code. Findings are reported as structured pass/fail output.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO / "plugins"

DANGEROUS_PATTERNS = [
    (re.compile(r"\beval\s*\("), "eval() call"),
    (re.compile(r"\bexec\s*\("), "exec() call"),
    (re.compile(r"\bpickle\.loads\s*\("), "pickle.loads()"),
    (re.compile(r"\bpickle\.load\s*\("), "pickle.load()"),
    (re.compile(r"\byaml\.load\s*\("), "yaml.load() without Loader"),
    (re.compile(r"__import__\s*\("), "__import__() call"),
]

# Allowlist: (relative_path_pattern, pattern_label)
# Intended for controlled subprocess/server starters where shell=True is safe.
ALLOWLIST = [
    ("plugins/tools/asgi_wsgi_tester.py", "subprocess shell=True"),
]


def _is_allowlisted(file_path: str, label: str) -> bool:
    for allowed_path, allowed_label in ALLOWLIST:
        if allowed_path in file_path and allowed_label == label:
            return True
    return False


def scan_file(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    for pattern, label in DANGEROUS_PATTERNS:
        for match in pattern.finditer(text):
            line_no = text[: match.start()].count("\n") + 1
            rel = str(path.relative_to(REPO))
            if _is_allowlisted(rel, label):
                continue
            findings.append({
                "file": rel,
                "line": line_no,
                "pattern": label,
                "snippet": text[max(0, match.start() - 40) : match.end() + 40].replace("\n", " "),
            })
    return findings


def scan_plugins(root: Path) -> dict[str, Any]:
    all_findings: list[dict[str, Any]] = []
    scanned = 0
    for py in root.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        findings = scan_file(py)
        if findings:
            all_findings.extend(findings)
        scanned += 1

    passed = len(all_findings) == 0
    return {
        "scanned_files": scanned,
        "findings": all_findings,
        "finding_count": len(all_findings),
        "pass": passed,
    }


def main() -> int:
    result = scan_plugins(PLUGINS_DIR)
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    import json
    raise SystemExit(main())
