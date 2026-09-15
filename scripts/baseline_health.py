#!/usr/bin/env python3
"""Baseline health one-liner for Cordi v2."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as exc:
        return exc.returncode, exc.output.strip()
    except FileNotFoundError as exc:
        return 127, str(exc)


def last_log_line(path: Path) -> str:
    if not path.exists():
        return "no-log"
    for enc in ("utf-16", "utf-8"):
        try:
            text = path.read_text(encoding=enc)
            lines = text.splitlines()
            line = lines[-1] if lines else "empty-log"
            return "".join(ch for ch in line if ch.isprintable() or ch in (" ", "\t")).strip()
        except Exception:
            continue
    return "unreadable"


def parse_log_summary(line: str) -> str:
    # Input: "2026-08-30 16:34:47 | baseline=OK passed=276 skipped=7 live=SKIPPED"
    if " | " in line:
        line = line.split(" | ", 1)[-1]
    return line.strip() or "n/a"


def parse_dry_run(output: str) -> str:
    # Input: "Dry run OK: profile=lite, plugins=21"
    for line in output.splitlines():
        if "Dry run OK:" in line:
            return line.split("Dry run OK:", 1)[-1].strip()
    return "unknown"


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    log_path = repo / "logs" / "baseline_gate.log"
    last_line = last_log_line(log_path)
    log_summary = parse_log_summary(last_line)

    rc_lite, out_lite = run([sys.executable, str(repo / "main.py"), "--profile", "lite", "--dry-run"])
    rc_cap, out_cap = run([sys.executable, str(repo / "scripts" / "capacity_calculator.py"), "--model", "1.5b", "--quiet"])

    lite = parse_dry_run(out_lite) if rc_lite == 0 else "FAIL"
    capacity = out_cap if rc_cap == 0 else "FAIL"

    status = "OK" if all([
        "baseline=OK" in last_line,
        lite != "FAIL",
        capacity != "FAIL",
    ]) else "FAIL"

    summary = (
        f"baseline=v2.0-baseline-stable "
        f"tests={log_summary} "
        f"live=n/a "
        f"capacity={capacity} "
        f"plugins={lite} "
        f"status={status}"
    )
    print(summary)
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
