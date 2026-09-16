"""MV-02 v2.1 monitor validity methodology qualification (implementation of the frozen specification).

Authoritative specification: benchmark/analysis/monitor_validity_v2_1.md (sha256 pinned below). The
instrument under test is the frozen scripts/resource_monitor_v1.py, which this package imports and never
modifies. Where this code and the specification disagree, the specification wins.

Components:
  mv02a_perturbation   MV-02A perturbation validity (paired child-internal duration)
  mv02b_measurement    MV-02B measurement/attribution validity (10 monitored invocations)
  mv02c_enforcement    MV-02C enforcement validity (C1-C10 against frozen v1 via ScriptedProbe)
  combine / run_all    execution order, stops and the combined verdict
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SPEC_PATH = ROOT / "benchmark" / "analysis" / "monitor_validity_v2_1.md"
SPEC_SHA256 = "e14b533363bee0bc946e6dfddbbfc516b1b195be3dbbbb8d75644c17eb0ae585"

MONITOR_V1_PATH = ROOT / "scripts" / "resource_monitor_v1.py"
MONITOR_V1_SHA256 = "a1940a1b2c03320b9ec9fd4abb6aba3b51f62011aaebec4dd66016a3cc997003"

# Epistemic verdicts of a component.
PASS, FAIL, UNRESOLVED = "PASS", "FAIL", "UNRESOLVED"
# Combined qualification outcome.
QUALIFIED = "QUALIFIED"
# Run status: outside every epistemic verdict. INVALID/ABNORMAL never maps to UNRESOLVED.
VALID, INVALID = "VALID", "INVALID"
NOT_RUN = "NOT_RUN"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
