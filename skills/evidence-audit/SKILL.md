---
id: evidence-audit
version: 1
---

# Skill: evidence-audit

## purpose
Verify that claims recorded in the log, knowledge records, decisions or reports are supported by frozen artifacts and are no stronger than their evidence scope.

## applies_when
- before writing an analysis section, Research Delta or Semantic Audit
- a metric looks surprising or contradicts a pre-registered expectation
- a report to the user cites numbers from experiments

## does_not_apply_when
- designing a new mechanism (heldout evidence is never tuning input here or anywhere)
- no recorded claim is being made or checked

## required_inputs
- the frozen scorer JSON output and stdout
- raw rows in `benchmark/results/repo_task_eval.jsonl`
- the gate file and the claim text being checked

## preconditions
- the scorer has run under its protocol (audit reads outputs; it never re-scores)
- read-only access: audit scripts write only to the scratchpad

## procedure
1. List each claim with its source: gated field, descriptive field, or trace observation.
2. Match every number against the frozen JSON output (arm, field, value); mismatches are errors in the document, not in the output.
3. Check provenance on the rows behind the claim: condition, split, gate sha256, harness sha256, model digest, row count per arm, no duplicate task rows within an arm.
4. Recompute hashes of the gate and scorer and compare with EXPERIMENT_LOG.md; run `python scripts/verify_frozen_artifacts.py`.
5. For descriptive claims about behavior, open the raw traces (calls, model_outputs, event records) and confirm the pattern on each claimed task, including round alignment between different record types.
6. Label each claim: supported (gated), supported (descriptive), overstated (narrow its wording and scope), or unsupported (remove it).
7. Check causal language and population: counts named with denominators; single-run and dev-only limits stated; no general claim from n of 2 to 8.
8. Record corrections and any scorer field flaws found, with the corrected descriptive values and their trace source.

## invariants
- Claims must never be stronger than their evidence scope.
- Gated claims and descriptive observations are labeled separately.
- Heldout failures are never used as tuning or design input.
- The audit never edits frozen artifacts or re-runs scorers.

## acceptance_criteria
- Every number in the checked text matches the frozen output or a cited trace computation.
- Every claim carries a label, and overstated claims were narrowed.
- Provenance, row counts and duplicates were checked for each arm cited.

## evidence_to_record
- claims checked with labels
- trace checks performed (tasks, fields, round alignment)
- corrections made to documents and scorer flaws documented

## failure_modes
- trusting a descriptive field without traces (EXP-21 re-engagement 0 was confirmed only after checking round alignment and model outputs)
- reading lane state as task success when the agent escalated (lane checks still run after escalation)
- citing heldout specifics as the reason for a dev design choice

## related_CAP_CON_METH_records
- METH-003
- METH-005
- METH-008
- METH-009
