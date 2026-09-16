"""MV-01: monitor-validity qualification protocol (S2, v1).

Answers an ENGINEERING EQUIVALENCE question, not a difference-detection question: does running the
250 ms resource monitor perturb the measured subprocess/resource channel by more than a
preregistered OPERATIONAL MARGIN?

The decision has three states and the protocol is frozen before it is executed on the machine:

  PASS        the preregistered uncertainty analysis places the whole confidence interval for the
              paired perturbation INSIDE the operational equivalence margin.
  FAIL        the interval lies entirely OUTSIDE the margin on one side: measured evidence supports
              perturbation beyond what is operationally allowed.
  UNRESOLVED  the interval straddles a margin boundary: the data cannot establish either conclusion.

Explicitly rejected reasoning, and none of it appears in this module:
  * p > 0.05 is NOT equivalence.
  * failure to reject is NOT proof of no overhead.
  * a post-hoc power calculation is NOT proof the trial was adequate.

Statistical method, preregistered: a distribution-free confidence interval for the median paired
difference, derived from the EXACT sign test (order statistics of the paired differences, exact
binomial coverage). It is assumption-light -- it does not assume symmetry or normality -- and it is
deliberately the conservative choice: at small n it is wide, so it returns UNRESOLVED rather than
over-claiming equivalence. Its relationship to the margin is direct: equivalence is concluded only
when the interval is contained in [-margin, +margin] (the interval-inclusion form of TOST).

Nothing here contacts a model, Ollama, or the benchmark corpus. The workload is synthetic.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024

# ----------------------------------------------------------------------------- frozen protocol

#: [POLICY] number of interleaved pairs. Each monitored observation has an adjacent unmonitored
#: counterpart, so temporal drift affects both members of a pair similarly.
PAIRS = 20

#: [POLICY] two-sided confidence level for the distribution-free interval.
ALPHA = 0.05

#: [POLICY] deterministic synthetic workload size. Chosen so one observation lasts on the order of a
#: few seconds on the machine of record: long enough that a 2% shift is meaningful, short enough that
#: 40 observations remain cheap. No model, no Ollama, no corpus.
WORKLOAD_ITERATIONS = 3_000_000
WORKLOAD_ALLOC_MIB = 64

#: Operational equivalence margins. Each is an OPERATIONAL BUDGET chosen in advance, never an
#: empirically derived threshold, and each is justified by what it would take to change a decision.
MARGINS: dict[str, dict[str, Any]] = {
    "duration_relative": {
        "margin": 0.02,
        "unit": "fraction of the unmonitored median duration",
        "label": "[POLICY]",
        "justification":
            "Operational budget. No resource gate, and no Stage-1 input, reads wall-clock duration at "
            "better than whole-second resolution, and the latency figures reported alongside are "
            "descriptive. A perturbation within 2% therefore cannot change any decision this "
            "methodology makes. It is an engineering allowance, not a measured property of the machine.",
    },
    "available_min_bytes": {
        "margin": 64 * MIB,
        "unit": "bytes of sampled AVAIL_MIN",
        "label": "[POLICY]",
        "justification":
            "Operational budget. 64 MiB is one eighth of the 512 MiB [POLICY] RESERVE, so a "
            "perturbation inside it can only flip the AVAIL_MIN >= RESERVE gate for runs already "
            "within 64 MiB of the threshold -- a proximity the artifact reports explicitly. It is an "
            "engineering allowance, not a measured property of the machine.",
    },
    "child_rss_bytes": {
        "margin": 16 * MIB,
        "unit": "bytes of child peak RSS",
        "label": "[POLICY]",
        "justification":
            "Operational budget for the measured child's own footprint. Nothing in the methodology "
            "gates on the child's RSS at finer resolution; it is reported as provenance. It is an "
            "engineering allowance, not a measured property of the machine.",
    },
}

#: [POLICY] direct absolute bound on the monitor's own footprint. Not a paired comparison.
MONITOR_RSS_CAP_BYTES = 64 * MIB

PASS, FAIL, UNRESOLVED = "PASS", "FAIL", "UNRESOLVED"


# ----------------------------------------------------------------------------- statistics (pure)

def sign_test_ci_rank(n: int, alpha: float = ALPHA) -> int | None:
    """Largest k with P(Bin(n, 1/2) <= k-1) <= alpha/2, giving the interval [d_(k), d_(n+1-k)].

    Returns None when n is too small for any interval at this alpha -- which is itself a reason to
    report UNRESOLVED rather than to loosen the criterion.
    """
    if n <= 0:
        return None
    target = alpha / 2
    best: int | None = None
    for k in range(1, n // 2 + 2):
        tail = sum(math.comb(n, i) for i in range(0, k)) / (2 ** n)
        if tail <= target:
            best = k
        else:
            break
    return best


def interval_coverage(n: int, alpha: float = ALPHA) -> float | None:
    """ACTUAL finite-sample coverage of the chosen order-statistic interval.

    Because the sign test is discrete, the attainable coverage is not exactly 1 - alpha. For the
    interval [d_(k), d_(n+1-k)] the exact coverage is 1 - 2 * P(Bin(n, 1/2) <= k-1). At n = 20 and
    alpha = 0.05 this is k = 6 and coverage 0.958611 (95.861%), i.e. CONSERVATIVE by 0.861
    percentage points -- never anti-conservative. The artifact reports this number rather than
    calling the interval "95%".
    """
    k = sign_test_ci_rank(n, alpha)
    if k is None:
        return None
    return 1 - 2 * sum(math.comb(n, i) for i in range(0, k)) / (2 ** n)


def distribution_free_ci(differences: Sequence[float], alpha: float = ALPHA) -> tuple[float, float] | None:
    """Exact sign-test confidence interval for the median paired difference.

    Order statistics: with rank k from `sign_test_ci_rank`, the interval is the closed interval
    between the k-th smallest and the k-th largest difference, i.e. 1-indexed [d_(k), d_(n+1-k)],
    implemented 0-indexed as [values[k-1], values[n-k]]. At n = 20, alpha = 0.05 that is
    [d_(6), d_(15)] = [values[5], values[14]].

    Assumptions: the paired differences are independent draws from a continuous distribution. Only
    the median is estimated -- no symmetry and no normality are assumed, so the method is genuinely
    distribution-free under those assumptions. TIES (which real timing data will contain, being
    discrete) do not break it: the interval remains valid and becomes CONSERVATIVE, because tied
    observations at the boundary can only widen the effective coverage. Even n needs no special
    handling: the interval is symmetric in the order statistics and never requires a middle element.

    The interval always discards the k-1 smallest and k-1 largest differences (5 of each at n = 20),
    so the narrowest interval it can return has width d_(15) - d_(6), which is zero when at least
    the middle ten differences coincide. PASS is therefore attainable, not vacuous.
    """
    values = sorted(differences)
    n = len(values)
    k = sign_test_ci_rank(n, alpha)
    if k is None or n < 2:
        return None
    return values[k - 1], values[n - k]


def hodges_lehmann(differences: Sequence[float]) -> float | None:
    """Descriptive point estimate (median of Walsh averages). Never used as the decision."""
    values = list(differences)
    if not values:
        return None
    walsh = [(values[i] + values[j]) / 2 for i in range(len(values)) for j in range(i, len(values))]
    return statistics.median(walsh)


def equivalence_decision(differences: Sequence[float], margin: float,
                         alpha: float = ALPHA) -> dict[str, Any]:
    """Three-state interval-inclusion equivalence decision.

    PASS       the whole interval lies inside (-margin, +margin).
    FAIL       the whole interval lies outside [-margin, +margin] on one side.
    UNRESOLVED anything else, including too few observations to form an interval.
    """
    interval = distribution_free_ci(differences, alpha)
    base = {
        "n": len(differences),
        "alpha": alpha,
        "margin": margin,
        "interval": list(interval) if interval else None,
        "point_estimate_hodges_lehmann": hodges_lehmann(differences),
        "order_statistic_rank_k": sign_test_ci_rank(len(differences), alpha),
        "actual_finite_sample_coverage": interval_coverage(len(differences), alpha),
        "method": "exact sign-test distribution-free CI for the median paired difference; "
                  "equivalence by interval inclusion. Coverage is DISCRETE: the reported "
                  "actual_finite_sample_coverage is the attainable value, not a nominal 1-alpha.",
    }
    if interval is None:
        return {**base, "decision": UNRESOLVED,
                "reason": "too few paired observations to form a confidence interval at this alpha"}
    low, high = interval
    if -margin < low and high < margin:
        return {**base, "decision": PASS,
                "reason": "the confidence interval lies entirely inside the operational margin"}
    if low >= margin or high <= -margin:
        return {**base, "decision": FAIL,
                "reason": "the confidence interval lies entirely outside the operational margin"}
    return {**base, "decision": UNRESOLVED,
            "reason": "the confidence interval straddles a margin boundary; the data establish "
                      "neither equivalence nor exceedance"}


def combine_decisions(decisions: Mapping[str, Mapping[str, Any]],
                      monitor_rss_bytes: int | None) -> dict[str, Any]:
    """FAIL dominates; then UNRESOLVED; PASS only when every quantity passes."""
    states = [d["decision"] for d in decisions.values()]
    monitor_ok = monitor_rss_bytes is not None and monitor_rss_bytes <= MONITOR_RSS_CAP_BYTES
    if FAIL in states or (monitor_rss_bytes is not None and not monitor_ok):
        overall = FAIL
    elif UNRESOLVED in states or monitor_rss_bytes is None:
        overall = UNRESOLVED
    else:
        overall = PASS
    return {
        "overall": overall,
        "per_quantity": {name: d["decision"] for name, d in decisions.items()},
        "monitor_rss_bytes": monitor_rss_bytes,
        "monitor_rss_cap_bytes": MONITOR_RSS_CAP_BYTES,
        "monitor_rss_within_cap": monitor_ok if monitor_rss_bytes is not None else None,
        "note": "PASS requires every quantity to be shown equivalent within its preregistered "
                "operational margin. Failure to reject a difference is never treated as equivalence.",
    }


# ----------------------------------------------------------------------------- synthetic workload

WORKLOAD_SOURCE = """\
import sys, time
iterations = int(sys.argv[1]); alloc_mib = int(sys.argv[2])
block = bytearray(alloc_mib * 1024 * 1024)
total = 0
for i in range(iterations):
    total = (total + i * i) % 1_000_003
    if (i & 0xFFFFF) == 0:
        block[(i // 0x100000) % len(block)] = total & 0xFF
print(total)
"""


def workload_command(script: Path) -> list[str]:
    return [sys.executable, str(script), str(WORKLOAD_ITERATIONS), str(WORKLOAD_ALLOC_MIB)]


def write_workload(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "mv01_workload.py"
    script.write_text(WORKLOAD_SOURCE, encoding="utf-8", newline="\n")
    return script


# ----------------------------------------------------------------------------- execution

def run_unmonitored(command: Sequence[str]) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(list(command), capture_output=True, text=True)
    return {"duration_seconds": time.monotonic() - started, "returncode": proc.returncode,
            "child_rss_bytes": None, "available_min_bytes": None}


def run_once_monitored(command: Sequence[str], scratch: Path) -> dict[str, Any]:
    from scripts import resource_monitor_v1 as rm  # noqa: WPS433 - local import keeps this optional

    started = time.monotonic()
    _state, artifact = rm.run_monitored(command, discover_ollama=False, cwd=ROOT)
    summary = artifact["summary"]
    return {
        "duration_seconds": time.monotonic() - started,
        "returncode": artifact["returncode"],
        "child_rss_bytes": summary.get("sampled_harness_rss_peak_bytes"),
        "available_min_bytes": summary.get("sampled_available_min_bytes"),
        "monitor_rss_bytes": summary.get("sampled_monitor_rss_peak_bytes"),
    }


def execute(scratch: Path, pairs: int = PAIRS) -> dict[str, Any]:
    """Interleaved paired trial: M,U,M,U,... so each monitored run has an adjacent counterpart."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    script = write_workload(scratch)
    command = workload_command(script)
    observations: list[dict[str, Any]] = []
    for index in range(pairs):
        monitored = run_once_monitored(command, scratch)
        unmonitored = run_unmonitored(command)
        observations.append({"pair": index, "monitored": monitored, "unmonitored": unmonitored})
    return analyse(observations)


def analyse(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pure: turn paired observations into the frozen three-state decision."""
    unmonitored_durations = [o["unmonitored"]["duration_seconds"] for o in observations]
    baseline = statistics.median(unmonitored_durations) if unmonitored_durations else 0.0

    duration_diffs = [
        (o["monitored"]["duration_seconds"] - o["unmonitored"]["duration_seconds"]) / baseline
        for o in observations
    ] if baseline > 0 else []

    # AVAIL_MIN and child RSS are only observed on monitored runs; the paired counterpart is the
    # unmonitored run's value where available. Where the unmonitored arm cannot supply the quantity
    # (the monitor is what measures it), the comparison is UNRESOLVED by construction rather than
    # silently skipped.
    avail_pairs = [(o["monitored"].get("available_min_bytes"), o["unmonitored"].get("available_min_bytes"))
                   for o in observations]
    rss_pairs = [(o["monitored"].get("child_rss_bytes"), o["unmonitored"].get("child_rss_bytes"))
                 for o in observations]
    avail_diffs = [m - u for m, u in avail_pairs if isinstance(m, int) and isinstance(u, int)]
    rss_diffs = [m - u for m, u in rss_pairs if isinstance(m, int) and isinstance(u, int)]

    decisions = {
        "duration_relative": equivalence_decision(duration_diffs, MARGINS["duration_relative"]["margin"]),
        "available_min_bytes": equivalence_decision(avail_diffs, MARGINS["available_min_bytes"]["margin"]),
        "child_rss_bytes": equivalence_decision(rss_diffs, MARGINS["child_rss_bytes"]["margin"]),
    }
    monitor_rss = [o["monitored"].get("monitor_rss_bytes") for o in observations
                   if isinstance(o["monitored"].get("monitor_rss_bytes"), int)]
    combined = combine_decisions(decisions, max(monitor_rss) if monitor_rss else None)
    return {
        "schema": "monitor_validity_v1",
        "protocol": {
            "pairs": len(observations),
            "alpha": ALPHA,
            "workload_iterations": WORKLOAD_ITERATIONS,
            "workload_alloc_mib": WORKLOAD_ALLOC_MIB,
            "interleaving": "M,U,M,U,... each monitored observation has an adjacent unmonitored counterpart",
            "margins": MARGINS,
            "monitor_rss_cap_bytes": MONITOR_RSS_CAP_BYTES,
        },
        "unmonitored_median_duration_seconds": baseline,
        "decisions": decisions,
        "result": combined,
        "observations": list(observations),
        "limitations": [
            "All extrema are SAMPLED values at the monitor's 250 ms interval, not continuous-time extrema.",
            "Quantities the unmonitored arm cannot observe yield no paired differences and are reported "
            "UNRESOLVED rather than assumed equivalent.",
            "If the platform cannot supply a stable signal for a quantity, that quantity is UNRESOLVED; "
            "no substitute measurement is manufactured.",
        ],
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="MV-01 monitor-validity qualification (synthetic, no model)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=PAIRS)
    args = parser.parse_args(argv)

    report = execute(args.scratch, pairs=args.pairs)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"overall": report["result"]["overall"],
                      "per_quantity": report["result"]["per_quantity"]}))
    return {PASS: 0, UNRESOLVED: 2, FAIL: 1}[report["result"]["overall"]]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
