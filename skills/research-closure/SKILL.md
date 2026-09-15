---
id: research-closure
version: 1
---

# Skill: research-closure

## purpose
Close a scored experiment consistently across EXPERIMENT_LOG, RESEARCH_YIELD, DECISIONS and PROJECT_TRACKING, so knowledge updates follow the frozen verdict and nothing is relabeled.

## applies_when
- the frozen scorer has run once for an experiment
- an experiment was stopped as INCONCLUSIVE and must still be closed

## does_not_apply_when
- runs are still in progress (use experiment-execution)
- the scorer has not run (use frozen-scorer)
- infrastructure-only changes (record as MNT, no Delta or Audit)

## required_inputs
- scorer stdout and frozen JSON output
- gate file with its pre-registered knowledge consequences
- raw rows for descriptive trace checks
- existing RESEARCH_YIELD records to update

## preconditions
- gate and scorer hashes were verified before the scoring run
- results files are append-only relative to the last commit
- no preset or default change has been made in anticipation of the verdict

## procedure
1. Record integrity: arms, row counts, harness and model digests, transient infrastructure events, hash confirmations, output paths.
2. Add an EXPERIMENT_LOG section "<gate> — integrity and raw results" with a per-arm table.
3. Add "<gate> — gate verdict (frozen scorer, unmodified)": V, MI, S, C and any recovery metric exactly as scored; the classification in bold.
4. Audit descriptive claims against raw traces (use evidence-audit) before writing the analysis; document scorer field flaws without patching.
5. Add "<gate> — analysis (separate from the verdict; descriptive unless stated)": mechanism, behavior, outcome, interpretation limits, next-bottleneck evidence.
6. Apply only the knowledge consequence the gate pre-registered for the obtained class; create or update CAP/CON/H/Q records with confidence and scoped `not_established`.
7. Update the registry row: log_section "<gate> — gate verdict", verdict, closure closed, updates, decision, delta yes, audit yes; set `active_experiment` accordingly.
8. Append "### Delta EXP-N" (BEFORE, RESULT, LEARNED, NOT LEARNED, UPDATED, SYSTEM CONSEQUENCE, ELIMINATED WORK, NEXT UNCERTAINTY) and "### Audit EXP-N" (DIRECTION, POPULATION, COMPARISONS, DESCRIPTIVE VS GATE, CONFOUNDS, CAUSAL LANGUAGE, NARROW FINDINGS, NARROW PASS).
9. Update DECISIONS (new bullet, previous one marked [Superseded]) and PROJECT_TRACKING (LAST COMPLETED GATE names the gate file; remove ACTIVE GATE when nothing is open; NEXT GATE text).
10. Preserve each file's existing line endings; run `python scripts/validate_research_state.py`.
11. Run `python scripts/verify_frozen_artifacts.py --write-manifest`, then `python scripts/verify_frozen_artifacts.py`; both must pass.
12. Commit the results, outputs and documents with a message stating the class; push; confirm the CI run.

## invariants
- A failed or partial experiment can still update knowledge, but cannot be relabeled as a capability success.
- No preset or default promotion unless the gate class supports it.
- Escalations and lane behavior are never counted as recovery or capability.
- Verdict sections report the scorer output unmodified; interpretation lives in the analysis section.

## acceptance_criteria
- Research-state validator and frozen-artifact verification pass.
- The registry row is closed with Delta and Audit present; knowledge records match the pre-registered consequence for the class.
- The CI run for the closure commit is green.

## evidence_to_record
- the three log sections, the Delta and the Audit
- manifest file count and row count from verification
- commit SHA and CI run result

## failure_modes
- validator R2 on multi-line record fields: keep record fields on one line
- R5/R7 stale active state (active_experiment or ACTIVE GATE still naming the closed experiment)
- knowledge wording broader than the tested population (fix wording, not the verdict)
- CRLF/LF mixing when appending to documents

## related_CAP_CON_METH_records
- METH-003
- METH-006
- METH-010
