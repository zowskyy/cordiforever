"""MV-02 machine-attempt orchestration: C (local parity) -> B -> A with the spec v2.1 §7 stops.

This is the entry point for a SEPARATELY APPROVED Windows machine attempt. It refuses to reuse an existing
attempt directory, never reruns anything, and writes one combined JSON result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import resource_monitor_v1 as rm  # noqa: E402
from scripts.monitor_validity_v2 import SPEC_SHA256, VALID, combine, mv02a_perturbation, mv02b_measurement  # noqa: E402
from scripts.monitor_validity_v2 import mv02c_enforcement  # noqa: E402


def run_all(attempt_dir: Path, *, c_case_runner: Callable[..., Any] | None = None, c_monitor: Any = rm,
            b_monitor_runner: Callable[..., Any] | None = None, b_child_factory: Callable[..., Any] | None = None,
            a_runner: Any = None) -> dict[str, Any]:
    attempt_dir = Path(attempt_dir)
    records, _provenance = mv02c_enforcement.run_suite(attempt_dir / "c", monitor=c_monitor,
                                                      case_runner=c_case_runner)
    c = {"component": "MV-02C", "cases": records, **mv02c_enforcement.evaluate(records)}
    b = a = None
    if combine.c_allows_continuation(c):
        b = mv02b_measurement.execute(attempt_dir / "b", monitor_runner=b_monitor_runner,
                                      child_factory=b_child_factory)
        if combine.b_allows_continuation(b):
            a = mv02a_perturbation.execute(attempt_dir / "a", runner=a_runner)
    return {"schema": "mv02_combined_v1", "spec_sha256": SPEC_SHA256, "C": c, "B": b, "A": a,
            "combined": combine.combine(c, b, a)}


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="MV-02 machine attempt (requires separate approval)")
    parser.add_argument("--attempt-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.attempt_dir.exists():
        print(f"refusing to reuse existing attempt directory {args.attempt_dir}")
        return 2
    args.attempt_dir.mkdir(parents=True)
    result = run_all(args.attempt_dir)
    (args.attempt_dir / "mv02_result.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str)
                                                       + "\n", encoding="utf-8")
    combined = result["combined"]
    print(f"MV02-RUN-STATUS: {combined['run_status']}")
    print(f"MV02-VERDICT: {combined['verdict']}")
    return 0 if combined["run_status"] == VALID else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
