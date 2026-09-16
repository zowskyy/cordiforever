"""Generic child programs used by MV-02, copied byte for byte into a scratch directory with their sha256.

The children are mechanically generic: every behaviour is an explicit command-line parameter. Evidence
POLICY (frozen X rule thresholds, 3.0 s holds, 250 ms sampling, invocation counts, timeouts) is owned by the
executors in mv02a_perturbation / mv02b_measurement, never by the children.

  child_a_workload.py    deterministic integer loop timed with time.perf_counter() after imports
  child_b_reference.py   reference working-set recorder: baseline / allocate / hold / release / final phases
  child_c_sleep.py       sleeps for a given time and exits with a given code
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

A_WORKLOAD = "child_a_workload.py"
B_REFERENCE = "child_b_reference.py"
C_SLEEP = "child_c_sleep.py"
CHILDREN = (A_WORKLOAD, B_REFERENCE, C_SLEEP)


def write_child(directory: Path, name: str) -> tuple[Path, str]:
    """Copy one child program into `directory`; return its path and the sha256 of the bytes written."""
    if name not in CHILDREN:
        raise ValueError(f"unknown MV-02 child program {name!r}")
    data = (PACKAGE_DIR / name).read_bytes()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()
