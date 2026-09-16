# MV-02 v2.1 — Monitor validity methodology qualification (preregistration)

- Registration identifier: MV-02
- Specification version: v2.1 (pre-execution correction of v2, benchmark/analysis/monitor_validity_v2.md sha256 3384f2332b7f44c4deb123573ea3889aa3da3f48ad95a174c8972f107a91c01e)
- Registration category: METHODOLOGY QUALIFICATION (repository type `methodology`; not an EXP- model experiment)
- Status at preregistration: REGISTERED / NOT IMPLEMENTED / NOT EXECUTED
- Date: 2026-09-16
- Repository HEAD at authoring: ceeb37b90d1c25a5070e71cc892b31bc884c5cad (tag s2-methodology-freeze)
- Instrument under test (frozen, never modified): scripts/resource_monitor_v1.py sha256 a1940a1b2c03320b9ec9fd4abb6aba3b51f62011aaebec4dd66016a3cc997003
- Predecessor protocol (frozen, never modified): scripts/monitor_validity_probe_v1.py sha256 b4d5d7ff27e3ba2783173f7211c7628a1cf354348886c0fe912ced95d03791d4

## 0.1 Version note (v2.1)

v2.1 is a pre-execution correction to frozen v2. Static pre-implementation review, before any MV-02 code existed, found:

1. C2 expected-result contradiction: v2 expected gate passed for a run with one sampled reading below reserve, but the frozen evaluate_gate requires the sampled minimum to be at or above reserve (as the v2 C3 and C5 rows themselves state).
2. C9 call-position contradiction: v2 placed the fault at sampler-loop processes() call 3 while also requiring 2 valid samples before the fault; under the frozen call order (2 processes() calls per sample) call 3 follows only 1 valid sample.
3. Underspecified C2, C3 and C5 sample indices.

At the time of this correction no C case had executed locally or on CI; A and B had not executed; no monitor, model, benchmark or scorer execution had occurred. v2 remains immutable and is PREREGISTERED / NEVER EXECUTED / SUPERSEDED BEFORE EXECUTION BY v2.1. v2.1 changes no observed-outcome interpretation because no outcome existed.

Changed in v2.1, and only these: the C2 expected gate result and classification; the C9 fault call number (3 to 5; exactly 2 valid samples before the fault); explicit indexing domains; the C2, C3 and C5 sample indices; version references.

v2.1 does NOT change: the C9 prediction; the A hypothesis, design, thresholds, sample counts, pair order or timeouts; the B hypothesis, design, thresholds, allocation policy, invocation count or timeouts; the C timeout; the statistical machinery; the combined verdict; the machine execution ordering; the lifecycle semantics; the heldout firewall.

## 0. Background and history

MV-01 was executed once on the machine of record (Attempt 2, directory cordii-qualification-2026-09-16-attempt2, runbook sha256 4E7A7B1633341489F4E89FCB9F2CCC47BDFB75143EA54C1682FDD416EFCA848F). Its result is and remains VALID FAIL UNDER MV-01. The run was valid under its preregistered protocol.

A read-only postmortem subsequently demonstrated methodology defects in MV-01:

- RC-1: PASS is unreachable on the MV-01 execution path. `run_unmonitored` returns None for available_min_bytes and child_rss_bytes, so those paired-difference lists are always empty, those quantities are always UNRESOLVED, and `combine_decisions` can never return PASS.
- RC-2: the MV-01 duration metric timed the external `run_monitored` wrapper (including per-run probe construction, preflight process snapshot and a `netstat` subprocess), not the child-internal `perf_counter` duration that CORDI persists as `seconds`.
- RC-3: the ±2% margin justification refers to downstream use of absolute harness-internal seconds but was applied as a relative fraction of wrapper time on a short synthetic task.
- RC-4: monitor observation correctness was framed as monitored-versus-unmonitored equivalence, which requires a reference the unmonitored arm cannot supply.
- RC-5: "PASS is attainable for every margin" was verified only on the pure decision helper, never on the combined execution path.
- RC-6: preflight runs a `netstat` subprocess in every monitored run even with discovery disabled (instrument behaviour; cost not measured).

Attempt 2's duration evidence is retained as a real measurement of wrapper timing. Attempt 1 remains INVALID_PRE_MEASUREMENT. Neither attempt is reinterpreted, relabelled or rerun.

Heldout disclosure: during the postmortem, the `seconds` field of 60 heldout rows of benchmark/results/repo_task_eval.jsonl was read incidentally by a duration scan. No other heldout field was read. Those values are not used anywhere in MV-02: no threshold, workload length, sample count or policy derives from heldout data.

Attempt exclusion: no Attempt 1 or Attempt 2 outcome value (durations, differences, intervals, RSS, AVAIL, monitor RSS, preflight readings) is used in any MV-02 threshold derivation. Attempt 2 exposed the defects above; it is not tuning data.

## 1. Hypotheses and scope

MV-02 consists of three independently falsifiable components. Machine and model resource viability (inference memory, AVAIL_MIN during inference, OOM, reserve viability, model footprint, monitor contention with the Ollama server) is OUTSIDE MV-02 and belongs to the later incumbent resource probe.

- H-A (perturbation validity): the frozen monitor does not shift the child-internal `perf_counter` duration by more than ±2% (median paired relative difference).
- H-B (measurement/attribution validity): for a controlled process tree, the median invocation-level allocation-hold attribution error of the frozen monitor is within ±16 MiB, the median invocation-level step error is within ±32 MiB, and within-invocation sampling pace meets policy.
- H-C (enforcement validity): the frozen enforcement path behaves as the pinned case table states, and no sampler failure yields `gate.passed == True`.

## 2. Development evidence used to choose methods (not MV-02 evidence)

- Python 3.12 documentation, `time`: monotonic() "Changed in version 3.5: The function is now always available and always system-wide"; "The reference point of the returned value is undefined, so that only the difference between the results of two calls is valid". perf_counter() "Changed in version 3.10: On Windows, the function is now system-wide."
- Environment: Python 3.12.14 (MSC v.1944 64 bit AMD64), Windows-11-10.0.26200-SP0.
- get_clock_info: monotonic implementation GetTickCount64(), resolution 0.015625 s, adjustable False; perf_counter implementation QueryPerformanceCounter(), resolution 1e-07 s.
- Two-process check (10 venv child processes, no monitor): 10/10 child monotonic readings lay within the parent's before/after bracket; parent-after minus child between 0.000 and 0.016 s.
- The venv interpreter `.venv\Scripts\python.exe` is a launcher: the real interpreter's parent process is the launcher executable. A venv-launched child is therefore a two-process tree.
- Exact sign-test ranks at alpha = 0.05: n=8 k=1; n=9 k=2 coverage 0.9609375; n=10 k=2 coverage 0.978515625; n=20 k=6 coverage 0.958610535 (reported 0.958611).
- Dev-only duration evidence: benchmark/results/repo_task_eval.jsonl split == dev, n = 560: min 4.9 s, p10 8.0 s, median 18.6 s, p90 55.4 s, max 236.0 s.

## 3. Downstream timing trace (basis for MV-02A)

- Timer start: benchmark/repo_task_eval.py `run_task`, first statement `started = time.perf_counter()`.
- Timed window: workspace seeding, application build, agent loop (model HTTP calls), registry stop, oracle, diff/analysis, row construction.
- Outside the window: interpreter startup, anything a monitor does before launching the harness process, row writing, summary.
- Persistence: `"seconds": round(time.perf_counter() - started, 1)`; no unrounded value is persisted.
- Harness summary: `round(sum(r["seconds"]), 1)`.
- benchmark/analysis/paired_substrate_v1.py `_resource_vector` copies `seconds`; `resource_comparison` reports `total_seconds = round(sum, 1)` per arm, labelled "never combined into a score".
- `classify_stage1` does not read `seconds`. `resource_viable` is a caller-supplied boolean; no code in the repository computes it from `seconds` or monitor output.
- Conclusion: `seconds` is descriptive. The 0.1 s is persistence/display rounding, not decision precision. No decision-derived tolerance exists; the MV-02A tolerance is therefore policy.

## 4. MV-02A — perturbation validity

Workload child (fixed source, launched through the venv launcher as in production): after imports it reads `t0 = time.perf_counter()`; runs a deterministic integer loop of I iterations with one 16 MiB buffer touched once at start; reads `t1`; prints JSON `{"child_seconds": t1 - t0, "child_seconds_rounded": round(t1 - t0, 1), "iterations": I}`.

Stated approximation: this matches the timer primitive and boundary placement of `run_task`, not its content. The real window is dominated by HTTP waits on Ollama; monitor contention with the Ollama server is not covered by MV-02A and belongs to the later resource probe.

Workload sizing (preregistered adaptive rule): before any pair, 3 unmonitored warm-up runs at I0 = 10,000,000 iterations; I = round(I0 × 8.0 / median(warm-up child_seconds)); I is fixed for the whole attempt and recorded; warm-ups are excluded from analysis.

Pairs: 20, numbered 1 to 20 in execution order (1-based); artifact field `pair_number` in {1, ..., 20}. Odd-numbered pairs (1, 3, ..., 19): M first, then U. Even-numbered pairs (2, 4, ..., 20): U first, then M. Thus pair 1 = M→U, pair 2 = U→M, ..., pair 20 = U→M.

- M = frozen `run_monitored(cmd, discover_ollama=False, cwd=ROOT, max_seconds=120)`.
- U = `subprocess.run(cmd, capture_output=True, text=True, timeout=120)`.
- Warm-ups use the U form with `timeout=120`.

Recorded per pair: child_seconds (unrounded and rounded) in both arms; parent-side wrapper wall time in both arms; relative difference (M − U) / median(U child_seconds over all 20 pairs) — GATING; absolute difference M − U in seconds — DESCRIPTIVE ONLY; monitor artifact summary — descriptive.

Decision: exact sign-test distribution-free confidence interval for the median paired relative difference; n = 20, alpha = 0.05, k = 6, interval [d(6), d(15)], actual coverage 0.958611; strict inclusion.

- PASS: -0.02 < low and high < 0.02.
- FAIL: low >= 0.02 or high <= -0.02.
- UNRESOLVED: otherwise.

INVALID (no verdict; stop; no automatic rerun) if any of: a child exits nonzero; child JSON missing or unparseable; in M a `watchdog_abort` or `timeout` event; in U `subprocess.TimeoutExpired`; any warm-up failure or timeout. Pairs are never dropped and no replacement pair is added.

Tolerance provenance: ±2% is [POLICY — INHERITED FROM FROZEN S2]. It existed before Attempts 1 and 2 and was not selected using their outcomes. It is retained as a conservative instrumentation-perturbation policy. It is not claimed to be derived from downstream decision precision, and not claimed to be the unique or mathematically necessary tolerance.

## 5. MV-02B — measurement/attribution validity

Unit of observation: the invocation. B executes 10 separate monitored child invocations numbered 1 to 10 in execution order. Each is a separate frozen `run_monitored(cmd, discover_ollama=False, cwd=ROOT, max_seconds=120)` call running exactly one controlled child launched through the venv launcher. Each invocation contains exactly one cycle:

1. baseline hold, 3.0 s
2. allocate X and touch every 4 KiB page
3. allocation hold, 3.0 s
4. release
5. final hold, 3.0 s

Controlled child and reference: the child records its own pid and its launcher (parent) pid. Every 250 ms by its own clock it records `GetProcessMemoryInfo(GetCurrentProcess()).WorkingSetSize` and the launcher's WorkingSetSize (OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION), each stamped with `time.monotonic()`, plus phase-transition timestamps, into a per-invocation sidecar JSONL. reference_tree_rss = self + launcher, matching the monitor's descendant sum rooted at the launched pid.

Independence limit: the reference uses the same Win32 API family as the monitor. B tests attribution (pid tree, summation, sampling timing, step capture), not the operating system's working-set accounting.

X determination:

- Invocation 1: immediately before allocation the child reads A0 = ullAvailPhys and applies: A0 >= 1296 MiB → X = 144 MiB; 1232 MiB <= A0 < 1296 MiB → X = 80 MiB; otherwise B = UNRESOLVED (PRECONDITION), no allocation occurs, and invocations 2 to 10 are recorded NOT RUN.
- The selected X is recorded and passed as a fixed argument to invocations 2 to 10.
- Invocations 2 to 10: immediately before allocation the child re-reads A0 and checks A0 >= X + 1152 MiB against the fixed X. X is never re-selected or resized. On failure the child records PRECONDITION_FAILED, does not allocate, exits 0, and that invocation is inadequate. Remaining invocations still run as numbered. No replacement invocation is added.
- No memory pressure is ever manufactured to obtain a result.

Alignment: timestamps plus guard band. A monitor sample belongs to a hold phase only if phase_start + G <= Sample.monotonic <= phase_end − G, with G = 0.5 s.

Adequate invocation: precondition passed; each of its three holds contains at least 4 in-window monitor samples; not INVALID.

Metrics:

- B1: per adequate invocation, median(monitor harness_rss_bytes in the allocation-hold window) − median(reference_tree_rss in the same window).
- B2: per adequate invocation, (monitor allocation-hold median − monitor baseline-hold median) − (reference allocation-hold median − reference baseline-hold median).
- Statistical claims: "B1 qualifies the median invocation-level allocation-hold attribution error against ±T." "B2 qualifies the median invocation-level step error against ±2T." Per-sample readings are inputs used to construct each invocation-level median. The interval does not establish that individual RSS readings are within ±T or ±2T.
- Descriptive only: AVAIL per sample and across phases (never a correctness oracle), per-pid tree composition, final-hold release behaviour.

B1/B2 decision: exact sign-test interval over invocation-level errors, n = 10 adequate invocations, alpha = 0.05, k = 2, interval [d(2), d(9)], coverage 0.978515625 (reported 0.978516), strict inclusion; B1 against ±T = ±16 MiB, B2 against ±2T = ±32 MiB. PASS / FAIL / UNRESOLVED as in section 4. Fewer than 10 adequate invocations → B1 and B2 UNRESOLVED. Independence is assumed across separate process invocations; shared system conditions (background load) remain a stated limitation.

B3 (sampling pace, within each invocation only): 8-consecutive-sample windows are formed only from samples of the same `run_monitored` invocation. No gap or window spans from the last sample of invocation N to the first sample of invocation N+1. Required invocations are those whose precondition passed. Ordered decision:

1. FAIL: any eligible within-invocation 8-sample window spans more than 3.5 s.
2. UNRESOLVED: otherwise, if any required invocation has fewer than 8 samples in total, unless a stronger INVALID condition applies to it.
3. PASS: otherwise.

B verdict: PASS iff B1, B2 and B3 are PASS; FAIL if any is FAIL; otherwise UNRESOLVED.

INVALID (no verdict; stop; no automatic rerun) if any of: child crash; sidecar missing or malformed; `watchdog_abort` or `timeout` event in any invocation; invocation pid tree inconsistent with its sidecar pids; A0 unreadable.

### 5.1 Derivation of X, tolerances and safety bound

T = 16 MiB [POLICY — INHERITED FROM FROZEN S2 child_rss_bytes budget].

A. Endpoint-error propagation. B2 differences two readings each allowed ±T. By the triangle inequality |e_alloc − e_base| <= 2T. B2 tolerance = 2T = 32 MiB (DERIVED).

B. Detectability. A monitor capturing only fraction f of a true step X has step error (1 − f)·X. B2 can FAIL it only if (1 − f)·X > 2T, i.e. X > 2T / (1 − f). [POLICY] target: fail any monitor capturing less than 75% of the step (1 − f = 0.25): X > 8T = 128 MiB; X_target = 9T = 144 MiB.

C. Minimum valid X. [POLICY] minimum: fail any monitor missing half the step (1 − f = 0.5): X > 4T = 64 MiB; X_min = 5T = 80 MiB. Below 2T = 32 MiB the test cannot fail even a monitor that misses the whole step; X_min is well above that floor.

D. Safety. RESERVE = 512 MiB (frozen). H = headroom = RESERVE = 512 MiB [POLICY]. O = unaccounted overhead allowance = frozen MONITOR_RSS_CAP 64 MiB + child-tree allowance 64 MiB [POLICY] = 128 MiB. Requirement A0 − X − O >= RESERVE + H, i.e. A0 >= X + 1152 MiB. X_target requires A0 >= 1296 MiB; X_min requires A0 >= 1232 MiB.

E. Precondition behaviour: as in section 5 X determination. Failure is UNRESOLVED (PRECONDITION) or an inadequate invocation, never pressure.

None of these values uses any observed AVAIL value from any attempt.

### 5.2 Derivation of the B3 pace policy

Nominal gap = frozen interval 0.25 s plus per-sample cost. The frozen watchdog aborts on the 8th consecutive sub-reserve sample, i.e. 7 gaps after the first sub-reserve sample. The frozen comment states the intent "~2 s at 250 ms" (8 × 0.25 s). [POLICY] allowance: each gap may average up to 2 × 0.25 s = 0.5 s to absorb sampling cost and scheduling slippage. Bound: every 8-consecutive-sample window (7 gaps) spans <= 7 × 0.5 = 3.5 s. Timestamp resolution 0.015625 s contributes at most 0.03125 s per span. This bound is [POLICY], not derived from the 250 ms interval alone.

## 6. MV-02C — enforcement validity

Instrument: frozen `run_monitored(cmd, probe=ScriptedProbe, discover_ollama=False, max_seconds=30)` with a real sleeping child and the default 0.25 s interval. Frozen v1 is not modified.

Test harness:

- ScriptedProbe implements the frozen SystemProbe interface via the supported `probe=` parameter. `available_memory_bytes()` returns values indexed by a call counter (call 0 = preflight). It can raise MonitorError on the Nth sampler-loop `processes()` call. `listener_pids` returns []. `committed_bytes` returns None.
- Indexing domains (distinct; never interchanged): the preflight available-memory read is call 0 of available_memory_bytes() and lies OUTSIDE the sample-index sequence; the available-memory SAMPLE INDEX is 0-based over samples taken by the sampler loop (the first sampled reading is sample index 0); the sampler-loop processes() CALL NUMBER is 1-based and counts only processes() calls made by the sampler loop (the preflight processes() call is excluded), so sample index i uses sampler-loop processes() calls 2i+1 and 2i+2; ScriptedProbe method-call counters are internal bookkeeping used only by the call-order self-check.
- Frozen call-order self-check: preflight shows 1 `processes()` and 1 `available_memory_bytes()` call; each sample shows 2 `processes()` calls then 1 `available_memory_bytes()` call. Mismatch → INVALID.
- Sampler-thread exceptions are captured by temporarily replacing `threading.excepthook`; sampler thread liveness after return is observed via `threading.enumerate()`.

Recorded per case: child outcome (returncode; completed / terminated / timeout); sampler outcome (NORMAL_STOP / WATCHDOG_RETURN / DIED_WITH_EXCEPTION(type) / STILL_ALIVE); sample count; watchdog outcome (abort sample index or none); events; exception outcome (none / propagated type); gate outcome (passed and conditions); safety classification.

Safety classifications:

| Class | Meaning | Acceptable |
|---|---|---|
| NOMINAL | pinned nominal behaviour (pass or abort) | yes, if matching |
| SAFE_GATE_FAIL | gate fails for a pinned, recorded reason | yes |
| EXCEPTION_PROPAGATED | run_monitored raised to the caller; no artifact | yes |
| SAMPLER_FAILURE_SURFACED | sampler failure visible in artifact/events and gate not passed | yes |
| SILENT_SAMPLER_DEATH_GATE_FAIL | sampler died without record; gate failed | yes for safety; flagged DIAGNOSTIC |
| SILENT_SAMPLER_DEATH_GATE_PASS | sampler died without record; gate.passed == True | never; C FAIL |

Case table (expected results pinned from frozen code, frozen comments and fail-closed policy):

| Case | Script | Child | Expected | Min samples for validity |
|---|---|---|---|---|
| C1 | all readings >= reserve + 1 GiB | sleep 3 s, exit 0 | NOMINAL: no abort, no events, gate passed | 4 |
| C2 | below reserve at sample index 1; all other readings above reserve | sleep 3 s | no watchdog abort (one isolated low reading does not satisfy the consecutive-low threshold); gate fails because sampled_available_min_at_or_above_reserve is False → SAFE_GATE_FAIL | 4 |
| C3 | below reserve at sample indices 1..7 inclusive; all other readings above reserve | sleep 4 s | no abort; gate fails on sampled_available_min_at_or_above_reserve → SAFE_GATE_FAIL | 9 |
| C4 | exactly 8 consecutive below starting at sample index 2 | sleep 10 s | abort at sample index 9; watchdog_abort event; child terminated; gate fails → NOMINAL abort | 10 |
| C5 | below reserve at sample indices 1..7 inclusive; above reserve at sample index 8; below reserve at sample indices 9..15 inclusive; all other readings above reserve | sleep 6 s | no abort (streak resets); gate fails on minimum → SAFE_GATE_FAIL | 16 |
| C6 | at least 10 readings exactly equal to reserve | sleep 4 s | not counted below (frozen strict <); no abort; gate passed → NOMINAL | 10 |
| C7a | first sampler reading None | sleep 3 s | fail-closed; not SILENT_SAMPLER_DEATH_GATE_PASS | 1 |
| C7b | 3 valid readings then None | sleep 3 s | fail-closed; not SILENT_SAMPLER_DEATH_GATE_PASS | 4 |
| C8 | all above; child sys.exit(3) after 2 s | — | nonzero_exit event; gate fails → SAFE_GATE_FAIL | 2 |
| C9 | probe raises MonitorError on sampler-loop processes() call 5 (sample index 0 uses calls 1 and 2 and completes; sample index 1 uses calls 3 and 4 and completes; call 5 begins sample index 2, raises, and that sample does not complete; exactly 2 valid samples before the fault); child continues sleeping 4 s, exit 0 | — | not SILENT_SAMPLER_DEATH_GATE_PASS | 2 before fault |
| C10 | probe raises on the first sampler-loop call | sleep 3 s | not SILENT_SAMPLER_DEATH_GATE_PASS | 0 |

Minimum samples not reached for a case → that case is INVALID, not FAIL.

STATIC PREDICTIONS (recorded before any execution; not demonstrated):

- C9 — POSSIBLE FAIL-OPEN SAMPLER-FAILURE PATH: the sampler loop in resource_monitor_v1.run_monitored has no try; the exception terminates the daemon thread without an event; the child continues without watchdog; summarize sees only the 2 valid samples; evaluate_gate passes if they are >= reserve and the child exits 0. Predicted classification SILENT_SAMPLER_DEATH_GATE_PASS → C FAIL.
- C10: zero samples → sampled_available_min_bytes UNKNOWN → gate fails. Predicted SILENT_SAMPLER_DEATH_GATE_FAIL (acceptable, DIAGNOSTIC).
- C7a: the None sample is appended, then `None < reserve` raises TypeError in the thread; summarize minimum is None, not int → gate fails. Predicted SILENT_SAMPLER_DEATH_GATE_FAIL (acceptable, DIAGNOSTIC).
- C7b: min over ints and None raises TypeError in summarize on the calling thread. Predicted EXCEPTION_PROPAGATED (acceptable).

C verdict model (two states plus INVALID):

- PASS: every case valid, matching its pinned expectation, and none SILENT_SAMPLER_DEATH_GATE_PASS.
- FAIL: any valid case mismatches, or any case is SILENT_SAMPLER_DEATH_GATE_PASS.
- INVALID/ABNORMAL (outside the epistemic verdict; stop for review): call-order self-check failure; minimum samples not reached; child spawn or harness error outside the run_monitored call.

If any case demonstrates SILENT_SAMPLER_DEATH_GATE_PASS: C = FAIL; MV-02 = FAIL; STOP. resource_monitor_v1 is not patched and MV-02 is not changed. A separate resource_monitor_v2 plan is presented for review.

Scope of C evidence: C isolates the resource-value inputs from platform memory conditions by using ScriptedProbe. The CI result is authoritative evidence for the frozen v1 control-flow/enforcement behavior in the CI environment. The local Windows parity run is required before MV-02 can support qualification of the Windows machine configuration.

- CI may establish C FAIL immediately; a CI C FAIL stops the sequence (no machine attempt; no supersession; separate resource_monitor_v2 plan).
- A CI C PASS does not by itself establish Windows parity.
- In the machine attempt, local C (C1 to C10, same table and classification) must PASS before B or A execute.
- A local C mismatch or INVALID stops the machine attempt before any memory allocation.
- MV-02 methodology acceptance (its own tests, mutations, reachability) is separate from C's verdict about v1.

## 7. Execution order and combined verdict

Machine attempt execution order:

1. local C parity (must PASS)
2. B invocations 1 to 10
3. A warm-ups, then pairs 1 to 20

Stops:

- CI C FAIL → no machine attempt.
- Local C FAIL or INVALID → stop; B and A recorded NOT RUN.
- B PRECONDITION at invocation 1 → B UNRESOLVED; invocations 2 to 10 NOT RUN; A still executes.
- INVALID/ABNORMAL in any component → stop; preserve; no verdict; no automatic rerun.

Combined verdict (only when no INVALID/ABNORMAL occurred): FAIL if any of A, B, C is FAIL; else UNRESOLVED if A or B is UNRESOLVED; else QUALIFIED. INVALID/ABNORMAL is a run status, never mapped to UNRESOLVED.

Knowledge consequences (fixed in advance):

- QUALIFIED supports validity of the frozen v1 monitor on the executed Windows machine configuration for: (a) perturbation of in-harness computation timing within ±2% (median paired relative difference); (b) median invocation-level allocation-hold attribution error within ±16 MiB and median invocation-level step error within ±32 MiB for a controlled process tree, with no claim about individual readings; (c) within-invocation sampling pace within policy; (d) enforcement control flow per the pinned table on CI and locally. It establishes nothing about inference memory, reserve viability or Ollama contention.
- FAIL names the component and blocks resource measurement with v1.
- UNRESOLVED names the metric and leaves qualification open; no rerun in the same attempt directory.

## 8. Vacuity and observability audit

| Metric | Producer | Consumer | Arm / reference | Possible values | Missing behaviour | PASS | FAIL | UNRESOLVED | INVALID / ABNORMAL |
|---|---|---|---|---|---|---|---|---|---|
| A relative difference | child JSON (M and U), pairs 1–20 in pinned order | mv02a.analyse | both arms | float | missing/bad JSON → INVALID | reachable | reachable | reachable (straddle) | child failure; M watchdog or 120 s timeout; U TimeoutExpired; warm-up failure/timeout |
| A absolute difference, rounded seconds, wrapper time | child JSON, parent clock | report | both arms | float | as above | descriptive | descriptive | descriptive | as above |
| X selection | invocation 1 pre-allocation A0 | mv02b.execute | invocation 1 | 144 / 80 / PRECONDITION | unreadable → INVALID | n/a | n/a | reachable (PRECONDITION) | reachable |
| Invocation adequacy (2–10) | child A0 re-check; in-window counts | mv02b.analyse | each invocation | adequate / inadequate | inadequate → excluded, not replaced | n/a | n/a | feeds B1/B2 UNRESOLVED | reachable |
| B1 median invocation-level allocation-hold attribution error | invocation medians of monitor samples and reference | mv02b.analyse | monitor vs reference tree, per invocation | int bytes per adequate invocation | <10 adequate → UNRESOLVED | reachable | reachable | reachable | crash; sidecar missing/malformed; pid mismatch; watchdog or 120 s timeout |
| B2 median invocation-level step error | same | mv02b.analyse | same | int bytes per adequate invocation | same | reachable | reachable | reachable | same |
| B3 pace | Sample.monotonic within each invocation | mv02b.analyse | monitor, per invocation; no cross-invocation gaps | float s per window | required invocation <8 samples → UNRESOLVED | reachable | reachable | reachable | same |
| B AVAIL | monitor | report | monitor | int | — | descriptive | descriptive | descriptive | — |
| C1–C10 (CI) | frozen v1 run_monitored + recorder on CI | mv02c.evaluate | pinned table | 6 classes + fields | not observable → INVALID | reachable (CI scope) | reachable (stops sequence) | not applicable | call-order check; min samples; harness error |
| C1–C10 (local parity) | same, on the Windows machine | mv02c.evaluate | pinned table | same | same | reachable (required before B, A) | reachable (stop) | not applicable | reachable (stop) |
| MV-02 combined | A, B, C verdicts | mv02.combine | — | QUALIFIED / FAIL / UNRESOLVED | any INVALID → no verdict | reachable | reachable | reachable | run status |

Rule: no gate metric may depend on a quantity its execution path cannot produce. Acceptance requires a test proving this against the real execute output schema.

## 9. Threshold provenance ledger

Excluded evidence for every row: all Attempt 1 and Attempt 2 outcome values; all heldout rows (including the 60 incidentally read heldout `seconds` values). Freeze date and specification sha256 are recorded in EXPERIMENT_LOG.md at registration.

| Threshold | Value | Units | Kind | Source / derivation | Allowed evidence |
|---|---|---|---|---|---|
| A tolerance | ±0.02 | relative to median U child_seconds | [POLICY — INHERITED FROM FROZEN S2] | conservative instrumentation policy predating all attempts; not decision-derived | frozen S2 text |
| A n / alpha / k / coverage | 20 / 0.05 / 6 / 0.958611 | — | [POLICY inherited]; k, coverage DERIVED | exact binomial | mathematics |
| A target duration | 8.0 | s | DERIVED | dev repo_task_eval p10, n = 560 | dev rows |
| A warm-up rule | 3 runs, I0 = 10,000,000, rescale to target | — | [POLICY] | adaptive sizing fixed before execution | — |
| A pair order | pairs 1–20, 1-based; odd M→U, even U→M | — | [POLICY] | drift balancing; indexing pinned | — |
| A timeout (warm-ups, M max_seconds, U timeout) | 120 | s | [POLICY] | 15× the 8.0 s target; hang protection only | 8.0 s target |
| T (B1 tolerance) | 16 | MiB | [POLICY — INHERITED FROM FROZEN S2] | frozen child_rss_bytes budget | frozen S2 |
| B2 tolerance | 32 (2T) | MiB | DERIVED | triangle inequality | mathematics |
| Detectability fractions | 0.25 target / 0.5 minimum | fraction of X | [POLICY] | fail monitors capturing <75% / <50% of step | — |
| X_target / X_min | 144 / 80 | MiB | DERIVED from T and policy fractions | X > 2T/(1 − f), next multiple of T above bound | mathematics |
| H | 512 | MiB | [POLICY] | one full frozen RESERVE of headroom | frozen RESERVE |
| O | 128 | MiB | [POLICY] | frozen monitor cap 64 + child-tree allowance 64 | frozen cap |
| Precondition | A0 >= X + 1152 (1296 for 144; 1232 for 80) | MiB | DERIVED | section 5.1 D | mathematics |
| X fixing rule | selected at invocation 1; invocations 2–10 re-check, never resize | — | [POLICY] | identical step across observations | — |
| Hold / G / min in-window samples | 3.0 s / 0.5 s / 4 per hold | — | [POLICY] (G = 2 intervals) | frozen 0.25 s interval; tick 0.015625 s | frozen S2; docs; clock info |
| B unit / n / alpha / k / coverage | separate monitored invocation, 1 cycle / 10 / 0.05 / 2 / 0.978515625 (reported 0.978516) | — | [POLICY] unit and n; k, coverage DERIVED | n = 9 is the minimum with k >= 2 | mathematics |
| B timeout (max_seconds per invocation) | 120 | s | [POLICY] | about 13× the 9 s of holds; hang protection only | spec phase durations |
| B3 span bound | 3.5 s per 8-sample window, within each invocation only | s | [POLICY] | 7 gaps × (2 × 0.25 s) | frozen interval and streak length |
| C timeout (max_seconds) | 30 | s | [POLICY] | above longest case child (10 s) | case table |
| C expected results | section 6 table | — | frozen contract + [POLICY] fail-closed | resource_monitor_v1 watchdog, evaluate_gate, run_monitored source | frozen S2 code |

## 10. Methodology acceptance (before MV-02 is frozen as accepted)

Seams in new code only: mv02a.execute(runner=), mv02b.execute(monitor_runner=, child_factory=), mv02c.evaluate(case_runner=), mv02.run_all(...).

Reachability through the combined path run_all → combine with injected runners:

- QUALIFIED: A equal durations; B perfect attribution and regular pace over 10 invocations; C injected all-matching case records.
- FAIL: A monitored × 1.10; B1 +2T offset; B2 missed step; B3 1.0 s gaps within an invocation; C injected SILENT_SAMPLER_DEATH_GATE_PASS record; each → FAIL.
- UNRESOLVED: A straddling; B 9 adequate invocations; B PRECONDITION at invocation 1; each → UNRESOLVED.
- INVALID: child crash record; C call-order self-check failure; U TimeoutExpired → run status INVALID, no verdict.
- B3 boundary test: a large gap between the last sample of one invocation and the first of the next must not affect B3.
- Vacuity test: from the real execute output schema, every gate metric in section 8 has a producer emitting a non-missing value in its declared arm or reference.

Mutation plan (scratch process; anchors asserted to match exactly once):

| Target | Mutations | Must be caught by |
|---|---|---|
| mv02a | swap M/U; gate on wrapper time; non-strict inclusion; silently drop invalid pairs; zero-based parity | FAIL/INVALID reachability; pair-order test |
| mv02b | omit launcher from reference; G = 0; no page touch; B2 tolerance = T; X re-selected per invocation; replacement invocation added; B3 windows across invocations | B1/B2/B3/PRECONDITION/boundary tests |
| mv02c | accept silent death with pass; ignore captured thread exceptions; min-samples shortfall as FAIL | C9 record test; INVALID test |
| frozen v1 (in memory only) | WATCHDOG_CONSECUTIVE_SAMPLES = 7; `<` → `<=`; streak not reset | C3/C4; C6; C5 |
| combine | UNRESOLVED as QUALIFIED; INVALID as UNRESOLVED; C FAIL not stopping B and A | combined reachability tests |

Every surviving mutation is shown equivalent with a demonstration or closed by a new test.

## 11. CI and local split

CI (existing S2 suite step; deterministic; no model; no evidence writes): A/B analysis and reachability tests; C1–C10 against the real frozen v1 (authoritative in CI scope; C FAIL stops the sequence); vacuity test; verify_frozen_artifacts.py; validate_research_state.py.

Local: narrow tests; mutation runs in scratch. Later, only after separate approval, one machine attempt in a new directory: local C parity (~1 min), B (~2–2.5 min), A (~5.5–6 min); total ~9–10 min; sequential; peak extra memory one child tree with X <= 144 MiB plus monitor, bounded by O. No cost-shape calibration.

Not part of MV-02: fixed-versus-proportional wrapper-cost calibration (retained only as a possible future research question).

## 12. Lifecycle and status states

State 1 (current, recorded at registration):

- MV-01: DEFECT CONFIRMED — REPLACEMENT IN DEVELOPMENT
- Attempt 2: VALID FAIL UNDER MV-01

State 2 (after MV-02 methodology acceptance + CI + freeze):

- MV-01: DEFECT CONFIRMED — QUALIFIED REPLACEMENT NOT YET ESTABLISHED
- MV-02: METHODOLOGY FROZEN — WINDOWS QUALIFICATION NOT YET EXECUTED

State 3 (after the separately approved Windows machine attempt), only if the combined result is QUALIFIED:

- MV-01: SUPERSEDED BY MV-02
- MV-02: WINDOWS QUALIFIED — <machine/environment scope: OS build, Python version, venv launcher, repository commit, instrument sha256, attempt directory>

If the Windows attempt produces FAIL, UNRESOLVED, INVALID or ABNORMAL: MV-02 is not called the qualified replacement; MV-01 is not superseded; the resulting state is preserved exactly and work stops for review. A CI C FAIL likewise prevents machine execution and prevents supersession.

Methodology validity (coherent, non-vacuous, preregistered, able to falsify the frozen monitor) is established by acceptance, CI and freeze. Target-machine qualification is established only by the Windows attempt result.

Lifecycle order:

1. Register this specification: hash; append registration records; State 1 wording.
2. Implement MV-02 in new files.
3. Narrow tests.
4. Mutation tests.
5. Combined reachability and vacuity tests.
6. Push; CI.
7. If CI C = FAIL: stop; resource_monitor_v2 plan; no machine attempt; no supersession.
8. If all methodology acceptance gates pass: freeze accepted MV-02 code and evidence; append State 2 wording.
9. STOP.
10. Separate plan and review for the machine-execution runbook (local C parity first).
11. After the attempt: State 3 wording only if QUALIFIED; otherwise preserve and stop.

## 13. Stop conditions

- The specification changes after hashing without a new version file.
- Any threshold would require Attempt outcome values or heldout data.
- Any combined state (QUALIFIED / FAIL / UNRESOLVED) or INVALID is unreachable, or the vacuity test fails.
- A surviving mutation is neither shown equivalent nor closed by a test.
- The C call-order self-check fails against v1 → INVALID; revise the harness design, never v1.
- Any C case is SILENT_SAMPLER_DEATH_GATE_PASS → C FAIL → MV-02 FAIL → STOP → separate resource_monitor_v2 plan.
- An edit would touch a frozen path, or frozen-artifact verification fails.
- The same blocker defeats two distinct methods → BLOCKED report.
- Machine attempt: any INVALID/ABNORMAL → stop, preserve, no rerun; local C mismatch/INVALID → stop before B and A; PRECONDITION → UNRESOLVED, never manufactured pressure.

## 14. Immutable artifacts

Never modified by MV-02: scripts/resource_monitor_v1.py; scripts/monitor_validity_probe_v1.py; tests/test_resource_monitor_v1.py; all frozen S2 paths; tag s2-methodology-freeze; Attempt 1 directory; Attempt 2 directory.

## 15. Applicable skills

- experiment-preregistration (formally, adapted): hypotheses; provenance-recorded thresholds; fixed sample counts; exhaustive ordered outcomes; knowledge consequences fixed in advance; specification hashed before code; revisions as new version files; no heldout design input. Not applied: arms, drift arm, model digest, EXP registry row, active_experiment.
- mutation-testing: section 10 mutation plan.
- ci-offload: section 11; no inference in CI.
- evidence-audit: every number cited in registration records checked against artifacts before appending.
- Not applicable: experiment-execution, frozen-scorer, research-closure.
- Frozen methodology rules override skill guidance on conflict.
