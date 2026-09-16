"""Exact sign-test distribution-free interval and strict-inclusion equivalence decision (spec v2.1 §4, §5).

Re-derived from the specification; nothing is imported from the superseded MV-01 module.

  rank k      largest k with P(Bin(n, 1/2) <= k - 1) <= alpha / 2
  interval    [d_(k), d_(n+1-k)] over the sorted differences (1-based order statistics)
  coverage    1 - 2 * P(Bin(n, 1/2) <= k - 1), the attainable discrete coverage
  PASS        -margin < low and high < margin
  FAIL        low >= margin or high <= -margin
  UNRESOLVED  otherwise, or when no interval exists
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Sequence

from scripts.monitor_validity_v2 import FAIL, PASS, UNRESOLVED

ALPHA = 0.05


def _lower_tail(n: int, k: int) -> float:
    return sum(math.comb(n, i) for i in range(0, k)) / (2 ** n)


def sign_test_rank(n: int, alpha: float = ALPHA) -> int | None:
    if n <= 0:
        return None
    best: int | None = None
    for k in range(1, n // 2 + 2):
        if _lower_tail(n, k) <= alpha / 2:
            best = k
        else:
            break
    return best


def coverage(n: int, alpha: float = ALPHA) -> float | None:
    k = sign_test_rank(n, alpha)
    return None if k is None else 1 - 2 * _lower_tail(n, k)


def interval(differences: Sequence[float], alpha: float = ALPHA) -> tuple[float, float] | None:
    values = sorted(differences)
    n = len(values)
    k = sign_test_rank(n, alpha)
    if k is None or n < 2:
        return None
    return values[k - 1], values[n - k]


def equivalence_decision(differences: Sequence[float], margin: float, *, n_required: int,
                         alpha: float = ALPHA) -> dict[str, Any]:
    """Three-state strict-inclusion decision. Fewer than `n_required` observations is UNRESOLVED."""
    n = len(differences)
    base: dict[str, Any] = {
        "n": n, "n_required": n_required, "alpha": alpha, "margin": margin,
        "rank_k": sign_test_rank(n, alpha), "coverage": coverage(n, alpha),
        "interval": None, "median": statistics.median(differences) if differences else None,
    }
    if n < n_required:
        return {**base, "decision": UNRESOLVED, "reason": f"{n} observations; {n_required} required"}
    bounds = interval(differences, alpha)
    if bounds is None:
        return {**base, "decision": UNRESOLVED, "reason": "no interval at this alpha"}
    low, high = bounds
    base["interval"] = [low, high]
    if -margin < low and high < margin:
        return {**base, "decision": PASS, "reason": "interval strictly inside the margin"}
    if low >= margin or high <= -margin:
        return {**base, "decision": FAIL, "reason": "interval entirely outside the margin"}
    return {**base, "decision": UNRESOLVED, "reason": "interval straddles or touches a margin boundary"}
