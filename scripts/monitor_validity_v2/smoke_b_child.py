"""B CHILD SMOKE — ENGINEERING ONLY — NOT MV-02 EVIDENCE.

Runs the SAME generic B child used by MV-02B once, UNMONITORED, with a 16 MiB allocation and short holds,
to check mechanics only: the process starts, allocation/touch succeeds, the sidecar is syntactically valid,
the expected phase records exist, pid fields exist, self/launcher working-set fields are nonzero, and the
child exits cleanly. It produces no B verdict, no monitor-accuracy evidence and no resource-viability evidence,
and it refuses to write inside any MV-02 evidence or machine-attempt location.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import children  # noqa: E402

SMOKE_LABEL = "B CHILD SMOKE — ENGINEERING ONLY — NOT MV-02 EVIDENCE"
SMOKE_ALLOC_MIB = 16
SMOKE_HOLD_S = 0.5
SMOKE_SAMPLE_INTERVAL_S = 0.25
SMOKE_TIMEOUT_S = 60
FORBIDDEN_PARTS = ("output_mv02", "cordii-qualification")


def check_output_path(path: Path) -> None:
    resolved = Path(path).resolve()
    text = resolved.as_posix()
    if any(part in text for part in FORBIDDEN_PARTS) or resolved.is_relative_to((ROOT / "benchmark").resolve()):
        raise ValueError(f"{SMOKE_LABEL}: refusing to write smoke output to an evidence location: {resolved}")


def build_smoke_command(child: Path, sidecar: Path) -> list[str]:
    return [sys.executable, str(child), "--sidecar", str(sidecar),
            "--baseline-hold", str(SMOKE_HOLD_S), "--alloc-hold", str(SMOKE_HOLD_S),
            "--final-hold", str(SMOKE_HOLD_S), "--sample-interval", str(SMOKE_SAMPLE_INTERVAL_S),
            "--alloc-mib", str(SMOKE_ALLOC_MIB)]


def evaluate_sidecar(records: Sequence[dict[str, Any]], returncode: int) -> dict[str, bool]:
    phases = {(r.get("phase"), r.get("event")) for r in records if r.get("kind") == "phase"}
    refs = [r for r in records if r.get("kind") == "ref"]
    start = next((r for r in records if r.get("kind") == "start"), {})
    end = next((r for r in records if r.get("kind") == "end"), {})
    return {
        "process_started": bool(start),
        "clean_exit": returncode == 0 and end.get("status") == "ok",
        "allocation_touch_completed": ("allocate", "end") in phases,
        "expected_phase_records_exist": all((name, event) in phases for name in
                                            ("baseline_hold", "allocate", "alloc_hold", "release", "final_hold")
                                            for event in ("start", "end")),
        "pid_fields_exist": all(isinstance(start.get(k), int) for k in ("pid", "launcher_pid", "launcher_parent_pid")),
        "working_set_fields_nonzero": bool(refs) and all((r.get("self_ws") or 0) > 0 and (r.get("launcher_ws") or 0) > 0
                                                         for r in refs),
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=SMOKE_LABEL)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    check_output_path(args.report)
    with tempfile.TemporaryDirectory(prefix="mv02-b-smoke-") as scratch:
        child, child_sha = children.write_child(Path(scratch), children.B_REFERENCE)
        sidecar = Path(scratch) / "smoke_sidecar.jsonl"
        proc = subprocess.run(build_smoke_command(child, sidecar), capture_output=True, text=True,
                              timeout=SMOKE_TIMEOUT_S)
        try:
            records = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()]
            syntactically_valid = True
        except (OSError, ValueError):
            records, syntactically_valid = [], False
    checks = {"sidecar_syntactically_valid": syntactically_valid, **evaluate_sidecar(records, proc.returncode)}
    report = {"label": SMOKE_LABEL, "evidentiary": False, "child_sha256": child_sha,
              "parameters": {"alloc_mib": SMOKE_ALLOC_MIB, "hold_s": SMOKE_HOLD_S,
                             "sample_interval_s": SMOKE_SAMPLE_INTERVAL_S, "monitored": False},
              "returncode": proc.returncode, "stderr_tail": proc.stderr[-2000:], "checks": checks,
              "all_checks_true": all(checks.values())}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(SMOKE_LABEL)
    print(json.dumps(checks, sort_keys=True))
    return 0 if report["all_checks_true"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
