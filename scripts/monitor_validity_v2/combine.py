"""MV-02 combined verdict and execution-order stops (spec v2.1 §7).

Order: local C parity -> B -> A.
  C FAIL or INVALID               -> stop; B and A NOT_RUN (C INVALID is a run status, no verdict)
  B INVALID                       -> stop; A NOT_RUN; no verdict
  B PRECONDITION at invocation 1  -> B UNRESOLVED; A still executes
  A INVALID                       -> no verdict
Combined verdict (only when no INVALID occurred): FAIL if any of A, B, C is FAIL; else UNRESOLVED if A or B is
UNRESOLVED; else QUALIFIED. INVALID/ABNORMAL is never mapped to UNRESOLVED.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.monitor_validity_v2 import FAIL, INVALID, NOT_RUN, PASS, QUALIFIED, UNRESOLVED, VALID


def c_allows_continuation(c: Mapping[str, Any]) -> bool:
    return c["run_status"] == VALID and c["c_verdict"] == PASS


def b_allows_continuation(b: Mapping[str, Any]) -> bool:
    return b["run_status"] == VALID


def combine(c: Mapping[str, Any], b: Mapping[str, Any] | None, a: Mapping[str, Any] | None) -> dict[str, Any]:
    components = {
        "C": {"run_status": c["run_status"], "verdict": c["c_verdict"]},
        "B": {"run_status": b["run_status"], "verdict": b["verdict"]} if b is not None else NOT_RUN,
        "A": {"run_status": a["run_status"], "verdict": a["verdict"]} if a is not None else NOT_RUN,
    }
    ran = [value for value in components.values() if value != NOT_RUN]
    if any(value["run_status"] == INVALID for value in ran):
        return {"run_status": INVALID, "verdict": None, "components": components}
    verdicts = {name: value["verdict"] for name, value in components.items() if value != NOT_RUN}
    if FAIL in verdicts.values():
        verdict = FAIL
    elif b is None or a is None:
        # Only reachable after a C FAIL (which returned above) or through an out-of-order caller.
        return {"run_status": INVALID, "verdict": None, "components": components,
                "reason": "B or A not run without a preceding stop condition"}
    elif UNRESOLVED in (verdicts["A"], verdicts["B"]):
        verdict = UNRESOLVED
    else:
        verdict = QUALIFIED
    return {"run_status": VALID, "verdict": verdict, "components": components}
