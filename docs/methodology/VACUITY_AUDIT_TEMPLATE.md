# Vacuity / observability audit — required acceptance artifact for methodology work

Origin: the MV-01 postmortem (RC-1, RC-5). MV-01 could never PASS on its real execution path because two gate
metrics were compared against an arm that structurally could not observe them, and the "PASS is attainable"
claim had been verified only on an isolated decision helper. Every future methodology that gates on metrics must
include this audit, and its reachability claims must be proven by tests that run the REAL top-level analysis path.

## 1. Gate-input table

One row per gate input. Descriptive-only quantities get their own rows marked `descriptive` in every verdict column.

| Metric | Producer | Consumer | Observed in which arm / reference | Possible values | Missing-value behaviour | PASS reachable? | FAIL reachable? | UNRESOLVED reachable? | INVALID / ABNORMAL behaviour |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

Rules:

- No gate metric may depend on a quantity its execution path cannot produce (e.g. a quantity only the monitor
  observes cannot be compared against an unmonitored arm).
- "Reachable" means reachable through the real top-level path (executor -> analysis -> combined verdict) with
  injected inputs, not through a pure helper in isolation.
- A component need not have every epistemic state; state explicitly which states it has and why.
- INVALID / ABNORMAL is a run status outside the epistemic verdict and is never mapped to UNRESOLVED.

## 2. Reachability proof

List the tests that drive the real top-level path to each reachable state:

| State | Trigger | Test (file::name) |
|---|---|---|
| PASS / QUALIFIED | | |
| FAIL | | |
| UNRESOLVED | | |
| INVALID | | |

## 3. Descriptive-only confirmation

Name the test showing that changing every descriptive-only quantity leaves the combined verdict unchanged.

## 4. Example

MV-02 v2.1 (benchmark/analysis/monitor_validity_v2_1.md §8) with tests/test_mv02_vacuity.py and
tests/test_mv02_combined_reachability.py.
