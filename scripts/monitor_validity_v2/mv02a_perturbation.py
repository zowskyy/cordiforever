"""MV-02A perturbation validity (spec v2.1 §4).

Primary quantity: the child-internal time.perf_counter() duration (the timer primitive and boundary placement
of repo_task_eval.run_task). Gate: exact sign-test interval for the median paired RELATIVE difference
(M - U) / median(U) against ±2% [POLICY — INHERITED FROM FROZEN S2]. Absolute differences are descriptive.

Pairs are numbered 1..20 in execution order (1-based): odd pairs run M then U, even pairs run U then M.
Any child failure, missing/unparseable JSON, M watchdog/timeout, U TimeoutExpired or warm-up failure is
INVALID: pairs are never dropped and never replaced.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import resource_monitor_v1 as rm  # noqa: E402
from scripts.monitor_validity_v2 import INVALID, VALID, children, stats  # noqa: E402

FROZEN_A: dict[str, Any] = {
    "pairs": 20,
    "alpha": 0.05,
    "tolerance_relative": 0.02,
    "target_duration_s": 8.0,
    "warmups": 3,
    "warmup_iterations": 10_000_000,
    "timeout_s": 120,
}

OK = "ok"


class Runner(Protocol):
    def unmonitored(self, command: Sequence[str], timeout_s: float) -> dict[str, Any]: ...
    def monitored(self, command: Sequence[str], max_seconds: float) -> dict[str, Any]: ...


def read_result(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"child_seconds": float(document["child_seconds"]),
                "child_seconds_rounded": document["child_seconds_rounded"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


class RealRunner:
    """Frozen run_monitored for M; subprocess.run with a parent-side timeout for U.

    The frozen run_monitored captures and discards the child's stdout, so BOTH arms read the child's JSON from
    the result file named on its command line (the last two arguments are `--result-file <path>`).
    """

    @staticmethod
    def _result_path(command: Sequence[str]) -> Path:
        return Path(command[list(command).index("--result-file") + 1])

    def unmonitored(self, command: Sequence[str], timeout_s: float) -> dict[str, Any]:
        result_path = self._result_path(command)
        result_path.unlink(missing_ok=True)
        started = time.monotonic()
        try:
            proc = subprocess.run(list(command), capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "wrapper_seconds": time.monotonic() - started}
        wrapper = time.monotonic() - started
        if proc.returncode != 0:
            return {"status": f"nonzero_exit({proc.returncode})", "wrapper_seconds": wrapper}
        parsed = read_result(result_path)
        if parsed is None:
            return {"status": "bad_json", "wrapper_seconds": wrapper}
        return {"status": OK, "wrapper_seconds": wrapper, **parsed}

    def monitored(self, command: Sequence[str], max_seconds: float) -> dict[str, Any]:
        result_path = self._result_path(command)
        result_path.unlink(missing_ok=True)
        started = time.monotonic()
        _state, artifact = rm.run_monitored(list(command), discover_ollama=False, cwd=ROOT,
                                            max_seconds=max_seconds)
        wrapper = time.monotonic() - started
        events = [e.get("event") for e in artifact["events"]]
        if artifact["watchdog_abort"] or "watchdog_abort" in events:
            return {"status": "watchdog_abort", "wrapper_seconds": wrapper}
        if "timeout" in events:
            return {"status": "timeout", "wrapper_seconds": wrapper}
        if artifact["returncode"] != 0:
            return {"status": f"nonzero_exit({artifact['returncode']})", "wrapper_seconds": wrapper}
        parsed = read_result(result_path)
        if parsed is None:
            return {"status": "bad_json", "wrapper_seconds": wrapper}
        return {"status": OK, "wrapper_seconds": wrapper, **parsed}


def pair_order(pair_number: int) -> tuple[str, str]:
    """1-based: odd pairs M then U; even pairs U then M."""
    if pair_number < 1:
        raise ValueError("pair numbers are 1-based")
    return ("M", "U") if pair_number % 2 == 1 else ("U", "M")


def execute(scratch: Path, *, runner: Runner | None = None) -> dict[str, Any]:
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    runner = runner or RealRunner()
    child, child_sha = children.write_child(scratch, children.A_WORKLOAD)
    timeout = FROZEN_A["timeout_s"]
    base = [sys.executable, str(child)]
    result_file = ["--result-file", str(scratch / "a_result.json")]

    warmups: list[dict[str, Any]] = []
    for index in range(1, FROZEN_A["warmups"] + 1):
        result = runner.unmonitored(base + ["--iterations", str(FROZEN_A["warmup_iterations"])] + result_file,
                                    timeout)
        warmups.append({"warmup": index, **result})
        if result["status"] != OK:
            return analyse({"child_sha256": child_sha, "warmups": warmups, "iterations": None, "pairs": []})
    median_warmup = statistics.median(w["child_seconds"] for w in warmups)
    iterations = round(FROZEN_A["warmup_iterations"] * FROZEN_A["target_duration_s"] / median_warmup)
    command = base + ["--iterations", str(iterations)] + result_file

    pairs: list[dict[str, Any]] = []
    for pair_number in range(1, FROZEN_A["pairs"] + 1):
        order = pair_order(pair_number)
        pair: dict[str, Any] = {"pair_number": pair_number, "order": list(order)}
        pairs.append(pair)
        for arm in order:
            result = runner.monitored(command, timeout) if arm == "M" else runner.unmonitored(command, timeout)
            pair[arm] = result
            if result["status"] != OK:
                return analyse({"child_sha256": child_sha, "warmups": warmups, "iterations": iterations,
                                "pairs": pairs})
    return analyse({"child_sha256": child_sha, "warmups": warmups, "iterations": iterations, "pairs": pairs})


def analyse(run: Mapping[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {"component": "MV-02A", "policy": FROZEN_A, **run}
    failures = [f"warmup {w['warmup']}: {w['status']}" for w in run["warmups"] if w["status"] != OK]
    for pair in run["pairs"]:
        for arm in ("M", "U"):
            if arm not in pair:
                failures.append(f"pair {pair['pair_number']} arm {arm}: not executed")
            elif pair[arm]["status"] != OK:
                failures.append(f"pair {pair['pair_number']} arm {arm}: {pair[arm]['status']}")
    if len(run["warmups"]) != FROZEN_A["warmups"] and not failures:
        failures.append(f"{len(run['warmups'])} warm-ups; {FROZEN_A['warmups']} required")
    if len(run["pairs"]) != FROZEN_A["pairs"] and not failures:
        failures.append(f"{len(run['pairs'])} pairs; {FROZEN_A['pairs']} required")
    if failures:
        return {**base, "run_status": INVALID, "verdict": None, "invalid_reasons": failures}
    unmonitored = [p["U"]["child_seconds"] for p in run["pairs"]]
    baseline = statistics.median(unmonitored)
    relative = [(p["M"]["child_seconds"] - p["U"]["child_seconds"]) / baseline for p in run["pairs"]]
    absolute = [p["M"]["child_seconds"] - p["U"]["child_seconds"] for p in run["pairs"]]
    decision = stats.equivalence_decision(relative, FROZEN_A["tolerance_relative"], n_required=FROZEN_A["pairs"],
                                          alpha=FROZEN_A["alpha"])
    return {**base, "run_status": VALID, "verdict": decision["decision"], "relative": decision,
            "unmonitored_median_child_seconds": baseline,
            "descriptive": {"absolute_differences_s": absolute, "absolute_median_s": statistics.median(absolute),
                            "wrapper_seconds": [{"pair_number": p["pair_number"], "M": p["M"]["wrapper_seconds"],
                                                 "U": p["U"]["wrapper_seconds"]} for p in run["pairs"]]}}
