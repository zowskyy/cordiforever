---
id: experiment-preregistration
version: 1
---

# Skill: experiment-preregistration

## purpose
Create a frozen experimental plan (gate file plus registry entry) before any mechanism code is written and before any treatment outcome is visible.

## applies_when
- a new experiment (EXP-N) is being designed
- a mechanism under evaluation is changed (this is a new gate `<name>_v2.md`, never an edit of `_v1`)
- a replication on another split is being planned

## does_not_apply_when
- the gate for the experiment is already frozen and runs are in progress (use experiment-execution)
- the change is harness maintenance that is not a treatment (record it as MNT/FND, outside any arm)
- the work is infrastructure only (CI, validators, skills)

## required_inputs
- the research question (Q-ID) and the hypothesis (H-ID) it tests, from RESEARCH_YIELD.md
- the user's decision on the single factor and any design choices that are genuinely theirs (base arm, abstention semantics, split)
- the frozen control rows: condition name, gate sha256, harness sha256, overrides sha256, registered values
- evidence used for design, restricted to the dev split

## preconditions
- the previous experiment is closed (registry `closure: closed`, Research Delta and Semantic Audit present) unless `parallel: yes`
- `python scripts/validate_research_state.py` passes before starting
- no mechanism code for the new factor exists yet
- no heldout task, row or failure pattern is used as design input

## procedure
1. Read the relevant CAP/CON/H/Q records and the last closure; state the hypothesis in one or two sentences, including the observed evidence that motivates it.
2. Name exactly one experimental factor as one calibration key; everything else is listed under "Unchanged".
3. Fix the arms: frozen control (condition, gate sha256, harness, overrides, registered values), treatment (control overrides plus the one key), and a drift arm (control condition rerun on the new harness) whenever the harness hash changes.
4. Write the mechanism precisely enough to test: triggers, state transitions, resets, release conditions, exact user-visible text (neutral: no file, line, fix or next-action hints).
5. Define validity V: row counts, one harness hash across treatment and drift, one model digest, single-factor overrides check, control equals registered values, drift within aggregate tolerances; trajectory identity is descriptive, never a V criterion.
6. Define mechanism integrity MI from a direct record (event or reconstructable replay), including bookkeeping invariants.
7. Define safety S with the existing bounds (damaged, false verified, insufficient-evidence false completion, stray, leaks, extraction without full read, localized hits).
8. Define capability C thresholds and any mechanism/recovery metric; derive any data-dependent threshold from frozen dev rows before freezing and record the computation.
9. Write the classes as an exhaustive ordered list (INCONCLUSIVE, FAIL, PASS, PARTIAL variants), the interpretation limits, the low-power caveat, the descriptive-only metrics, and the pre-registered knowledge consequence per class (scoped wording).
10. State the scorer plan (which frozen scorer is imported by hash, what is added) and the scope sentence (what the experiment does not test).
11. Save `benchmark/gates/<name>_v1.md`, compute its sha256, and add an EXPERIMENT_LOG.md section "<name> — pre-registration" with the hash and design evidence.
12. Register the EXP row (verdict PENDING, closure open), set `active_experiment`, add the ACTIVE GATE line in PROJECT_TRACKING.md and a DECISIONS bullet; run `python scripts/validate_research_state.py`.
13. Present the plan to the user in chat as plain text; apply requested tightening before hashing; do not implement until the gate is frozen.

## invariants
- No gate may be changed after treatment results are visible; a revision is a new `_vN` gate that reruns all arms.
- One factor per experiment; control, drift and treatment stay distinct.
- The heldout split is never design input.
- Escalation or abstention is never counted as task success.
- Knowledge consequences are fixed before the run and scoped to the population tested.

## acceptance_criteria
- The gate file exists, contains every section listed in the procedure, and its sha256 is logged in EXPERIMENT_LOG.md.
- The registry row is PENDING/open with the gate filename; the research-state validator passes.
- Every threshold is a number or a rule computed from frozen data recorded before freezing.
- The user has seen the full plan in chat.

## evidence_to_record
- gate path and sha256
- control provenance (gate, harness, overrides hashes and registered values)
- data-dependent threshold computations (inputs and result)
- design evidence (dev rows only) and user design decisions

## failure_modes
- implementation described with a weaker rule than the gate (e.g. "reset per turn" when the gate says per task): fix the text before hashing
- validity tied to exact trajectory identity: invalidates good runs on harmless instrumentation
- two factors bundled (e.g. a new action plus a new gate): split into separate experiments
- knowledge consequence worded more broadly than the population supports
- threshold chosen after seeing treatment rows

## related_CAP_CON_METH_records
- METH-002
- METH-003
- METH-004
- METH-009
