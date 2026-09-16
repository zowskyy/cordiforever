"""MV-02B measurement/attribution validity (spec v2.1 §5).

The EXECUTOR owns the frozen evidence policy: it builds every child command from FROZEN_B and accepts no
policy parameter from its caller. The generic B child (children.py) only does what its explicit arguments say.

Per invocation (10 separate frozen run_monitored calls, one cycle each):
  B1  median(monitor harness_rss in allocation-hold window) - median(reference tree RSS in the same window)
  B2  (monitor alloc median - monitor baseline median) - (reference alloc median - reference baseline median)
Statistical claims: B1 qualifies the median invocation-level allocation-hold attribution error against ±T; B2
qualifies the median invocation-level step error against ±2T. Per-sample readings only build those medians.
B3 evaluates 8-consecutive-sample windows strictly within each invocation; no window crosses invocations.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import resource_monitor_v1 as rm  # noqa: E402
from scripts.monitor_validity_v2 import FAIL, INVALID, NOT_RUN, PASS, UNRESOLVED, VALID, children, stats  # noqa: E402

MIB = 1024 * 1024

FROZEN_B: dict[str, Any] = {
    "invocations": 10,
    "baseline_hold_s": 3.0,
    "alloc_hold_s": 3.0,
    "final_hold_s": 3.0,
    "child_sample_interval_s": 0.25,
    "guard_band_s": 0.5,
    "min_in_window_samples": 4,
    "t_bytes": 16 * MIB,
    "b2_bytes": 32 * MIB,
    "x_target_mib": 144,
    "x_min_mib": 80,
    "reserve_mib": 512,
    "headroom_mib": 512,
    "overhead_mib": 128,
    "required_free_mib": 1152,
    "max_seconds": 120,
    "n_required": 10,
    "alpha": 0.05,
    "b3_window_samples": 8,
    "b3_max_span_s": 3.5,
}

HOLDS = ("baseline_hold", "alloc_hold", "final_hold")

MonitorRunner = Callable[[Sequence[str]], Mapping[str, Any]]
ChildFactory = Callable[[Path], Path]


def build_command(child: Path, sidecar: Path, *, invocation: int, fixed_x_mib: int | None) -> list[str]:
    """Child command for one evidence invocation, from FROZEN_B only."""
    command = [sys.executable, str(child), "--sidecar", str(sidecar),
               "--baseline-hold", str(FROZEN_B["baseline_hold_s"]),
               "--alloc-hold", str(FROZEN_B["alloc_hold_s"]),
               "--final-hold", str(FROZEN_B["final_hold_s"]),
               "--sample-interval", str(FROZEN_B["child_sample_interval_s"]),
               "--required-free-mib", str(FROZEN_B["required_free_mib"])]
    if invocation == 1:
        command += ["--select-x", "--x-target-mib", str(FROZEN_B["x_target_mib"]),
                    "--x-min-mib", str(FROZEN_B["x_min_mib"])]
    else:
        if fixed_x_mib is None:
            raise ValueError("invocations 2-10 require the X fixed at invocation 1")
        command += ["--fixed-x", str(fixed_x_mib)]
    return command


def default_monitor_runner(command: Sequence[str]) -> dict[str, Any]:
    state, artifact = rm.run_monitored(list(command), discover_ollama=False, cwd=ROOT,
                                       max_seconds=FROZEN_B["max_seconds"])
    return {
        "samples": [{"index": s.index, "monotonic": s.monotonic, "harness_rss_bytes": s.harness_rss_bytes,
                     "available_bytes": s.available_bytes} for s in state.samples],
        "events": artifact["events"], "watchdog_abort": artifact["watchdog_abort"],
        "returncode": artifact["returncode"],
    }


def default_child_factory(scratch: Path) -> Path:
    path, _sha = children.write_child(scratch, children.B_REFERENCE)
    return path


def read_sidecar(path: Path) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not path.is_file():
        return None, "sidecar missing"
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()], None
    except (ValueError, OSError) as exc:
        return None, f"sidecar malformed: {exc}"


def execute(scratch: Path, *, monitor_runner: MonitorRunner | None = None,
            child_factory: ChildFactory | None = None) -> dict[str, Any]:
    """Run invocations 1..10 under FROZEN_B; stop on INVALID or on the invocation-1 precondition."""
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    runner = monitor_runner or default_monitor_runner
    child = (child_factory or default_child_factory)(scratch)
    records: list[dict[str, Any]] = []
    fixed_x: int | None = None
    for invocation in range(1, FROZEN_B["invocations"] + 1):
        sidecar = scratch / f"b_invocation_{invocation:02d}.jsonl"
        command = build_command(child, sidecar, invocation=invocation, fixed_x_mib=fixed_x)
        observed = dict(runner(command))
        parsed, error = read_sidecar(sidecar)
        record = {"invocation": invocation, "command": command, "fixed_x_mib": fixed_x,
                  "harness_pid": os.getpid(), "sidecar": parsed, "sidecar_error": error, **observed}
        records.append(record)
        outcome = analyse_invocation(record)
        if outcome["status"] == INVALID:
            break
        if invocation == 1:
            if outcome["status"] == "PRECONDITION_FAILED":
                break
            fixed_x = outcome["x_mib"]
    return analyse(records)


def _phase_bounds(sidecar: Sequence[Mapping[str, Any]]) -> dict[str, tuple[float, float]]:
    starts = {r["phase"]: r["t"] for r in sidecar if r.get("kind") == "phase" and r.get("event") == "start"}
    ends = {r["phase"]: r["t"] for r in sidecar if r.get("kind") == "phase" and r.get("event") == "end"}
    return {name: (starts[name], ends[name]) for name in starts if name in ends}


def analyse_invocation(record: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    out: dict[str, Any] = {"invocation": record["invocation"], "status": None, "x_mib": None, "b1_error": None,
                           "b2_error": None, "sample_times": [s["monotonic"] for s in record.get("samples", [])],
                           "in_window_counts": {}, "reasons": reasons}
    if record.get("returncode") != 0:
        reasons.append(f"child returncode {record.get('returncode')}")
    if record.get("watchdog_abort") or any(e.get("event") in ("watchdog_abort", "timeout")
                                          for e in record.get("events", [])):
        reasons.append("watchdog_abort or timeout event")
    sidecar = record.get("sidecar")
    if sidecar is None:
        reasons.append(record.get("sidecar_error") or "sidecar missing")
    if reasons:
        return {**out, "status": INVALID}
    start = next((r for r in sidecar if r.get("kind") == "start"), None)
    end = next((r for r in sidecar if r.get("kind") == "end"), None)
    precondition = next((r for r in sidecar if r.get("kind") == "precondition"), None)
    if start is None or end is None or precondition is None:
        return {**out, "status": INVALID, "reasons": ["sidecar incomplete (start/precondition/end missing)"]}
    if start.get("launcher_parent_pid") != record["harness_pid"]:
        return {**out, "status": INVALID,
                "reasons": ["pid tree inconsistent: launcher was not spawned by the monitoring process"]}
    if precondition.get("result") == "A0_UNREADABLE":
        return {**out, "status": INVALID, "reasons": ["A0 unreadable"]}
    if precondition.get("result") == "PRECONDITION_FAILED":
        return {**out, "status": "PRECONDITION_FAILED"}
    if precondition.get("result") != "OK":
        return {**out, "status": INVALID, "reasons": [f"unexpected precondition result {precondition.get('result')}"]}
    out["x_mib"] = precondition["x_mib"]
    if record["invocation"] > 1 and precondition["x_mib"] != record.get("fixed_x_mib"):
        return {**out, "status": INVALID, "reasons": ["X differs from the X fixed at invocation 1"]}

    refs = [r for r in sidecar if r.get("kind") == "ref"]
    if any(r.get("self_ws") is None or r.get("launcher_ws") is None for r in refs):
        return {**out, "status": INVALID, "reasons": ["reference working set unreadable"]}
    bounds = _phase_bounds(sidecar)
    if any(name not in bounds for name in HOLDS):
        return {**out, "status": INVALID, "reasons": ["hold phase markers missing"]}
    guard = FROZEN_B["guard_band_s"]
    monitor_medians: dict[str, float] = {}
    reference_medians: dict[str, float] = {}
    adequate = True
    for name in HOLDS:
        low, high = bounds[name][0] + guard, bounds[name][1] - guard
        mon = [s["harness_rss_bytes"] for s in record["samples"] if low <= s["monotonic"] <= high]
        ref = [r["self_ws"] + r["launcher_ws"] for r in refs if low <= r["t"] <= high]
        out["in_window_counts"][name] = len(mon)
        if len(mon) < FROZEN_B["min_in_window_samples"] or not ref:
            adequate = False
            continue
        monitor_medians[name] = statistics.median(mon)
        reference_medians[name] = statistics.median(ref)
    if not adequate:
        return {**out, "status": "INADEQUATE", "reasons": ["fewer than 4 in-window monitor samples in a hold"]}
    out["b1_error"] = monitor_medians["alloc_hold"] - reference_medians["alloc_hold"]
    out["b2_error"] = ((monitor_medians["alloc_hold"] - monitor_medians["baseline_hold"])
                       - (reference_medians["alloc_hold"] - reference_medians["baseline_hold"]))
    return {**out, "status": "ADEQUATE"}


def b3_decision(per_invocation: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Ordered FAIL -> UNRESOLVED -> PASS over windows strictly inside each invocation."""
    window, limit = FROZEN_B["b3_window_samples"], FROZEN_B["b3_max_span_s"]
    required = [p for p in per_invocation if p["status"] in ("ADEQUATE", "INADEQUATE")]
    worst: float | None = None
    exceeded: list[int] = []
    short: list[int] = []
    for p in required:
        times = p["sample_times"]
        if len(times) < window:
            short.append(p["invocation"])
            continue
        for i in range(len(times) - window + 1):
            span = times[i + window - 1] - times[i]
            worst = span if worst is None else max(worst, span)
            if span > limit:
                exceeded.append(p["invocation"])
                break
    if exceeded:
        decision = FAIL
    elif short or not required:
        decision = UNRESOLVED
    else:
        decision = PASS
    return {"decision": decision, "max_span_s": worst, "limit_s": limit, "exceeded_invocations": exceeded,
            "short_invocations": short}


def analyse(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    per = [analyse_invocation(r) for r in records]
    base: dict[str, Any] = {"component": "MV-02B", "policy": FROZEN_B, "invocations": per}
    invalid = [p for p in per if p["status"] == INVALID]
    if invalid:
        return {**base, "run_status": INVALID, "verdict": None,
                "invalid_reasons": [f"invocation {p['invocation']}: {r}" for p in invalid for r in p["reasons"]]}
    if per and per[0]["status"] == "PRECONDITION_FAILED":
        return {**base, "run_status": VALID, "verdict": UNRESOLVED, "reason": "PRECONDITION at invocation 1",
                "not_run_invocations": list(range(2, FROZEN_B["invocations"] + 1)),
                "b1": {"decision": UNRESOLVED}, "b2": {"decision": UNRESOLVED}, "b3": {"decision": UNRESOLVED}}
    if len(records) != FROZEN_B["invocations"]:
        return {**base, "run_status": INVALID, "verdict": None,
                "invalid_reasons": [f"{len(records)} invocations recorded; {FROZEN_B['invocations']} required"]}
    adequate = [p for p in per if p["status"] == "ADEQUATE"]
    b1 = stats.equivalence_decision([p["b1_error"] for p in adequate], FROZEN_B["t_bytes"],
                                    n_required=FROZEN_B["n_required"], alpha=FROZEN_B["alpha"])
    b2 = stats.equivalence_decision([p["b2_error"] for p in adequate], FROZEN_B["b2_bytes"],
                                    n_required=FROZEN_B["n_required"], alpha=FROZEN_B["alpha"])
    b3 = b3_decision(per)
    decisions = [b1["decision"], b2["decision"], b3["decision"]]
    verdict = FAIL if FAIL in decisions else (UNRESOLVED if UNRESOLVED in decisions else PASS)
    return {**base, "run_status": VALID, "verdict": verdict, "b1": b1, "b2": b2, "b3": b3,
            "adequate_invocations": len(adequate), "not_run_invocations": []}


__all__ = ["FROZEN_B", "NOT_RUN", "analyse", "analyse_invocation", "b3_decision", "build_command", "execute"]
