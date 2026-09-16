# MV-02 v2.1 implementation — tracking

## Purpose

Implements the frozen MV-02 v2.1 methodology qualification specification
(`benchmark/analysis/monitor_validity_v2_1.md`, sha256 e14b533363bee0bc946e6dfddbbfc516b1b195be3dbbbb8d75644c17eb0ae585):
MV-02A perturbation validity, MV-02B measurement/attribution validity and MV-02C enforcement validity of the frozen
`scripts/resource_monitor_v1.py`, plus the execution-order stops and combined verdict. The frozen monitor is the
instrument under test and is never modified. No machine qualification is authorized by this implementation.

## File inventory

| File | Purpose | Status |
|---|---|---|
| `__init__.py` | spec/monitor pins, verdict and run-status constants | complete |
| `stats.py` | exact sign-test interval, strict-inclusion decision | complete |
| `children.py` | copies generic child programs into scratch with sha256 | complete |
| `child_a_workload.py` | A workload: perf_counter-timed loop, JSON to stdout and `--result-file` | complete |
| `child_b_reference.py` | B reference child: phases, self+launcher working set, frozen X rule function | complete |
| `child_c_sleep.py` | C child: sleep then exit code | complete |
| `mv02a_perturbation.py` | A executor (FROZEN_A), real runner, analysis | complete; real A not executed |
| `mv02b_measurement.py` | B executor (FROZEN_B), analysis, B3 within invocations | complete; real B not executed |
| `mv02c_enforcement.py` | ScriptedProbe, excepthook recorder, C1-C10, classifier, evidence, CI-only CLI, CI status classifier | complete; first real C1-C10 run pending on CI |
| `combine.py` | execution-order stops and combined verdict | complete |
| `run_all.py` | machine-attempt orchestration (requires separate approval) | complete; not invoked |
| `smoke_b_child.py` | B CHILD SMOKE — ENGINEERING ONLY — NOT MV-02 EVIDENCE | complete; run once locally |
| `mutations.py` | local and CI-only frozen-v1 in-memory mutation runner | complete |

Tests: `tests/test_mv02_stats.py`, `tests/test_mv02a.py`, `tests/test_mv02b.py`, `tests/test_mv02b_policy_isolation.py`,
`tests/test_mv02c_local.py`, `tests/test_mv02_combined_reachability.py`, `tests/test_mv02_vacuity.py`,
`tests/test_mv02_spec_pin.py`, `tests/test_mv02_mutations.py`, shared fixtures `tests/mv02_fixtures.py` — complete.

## Open dependencies

- First real C1-C10 execution against frozen v1 on CI and preservation of its evidence artifact.
- Methodology acceptance freeze (only if C PASS) — requires separate review.
- Windows machine attempt (local C parity, B, A) — requires separate approval.

## Known gaps

- The B child's Windows API path is exercised only by the non-evidentiary engineering smoke run and, later, by the
  approved machine attempt; CI (Linux) covers its pure X-rule and page-touch functions only.
