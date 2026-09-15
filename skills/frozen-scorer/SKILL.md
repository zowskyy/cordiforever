---
id: frozen-scorer
version: 1
---

# Skill: frozen-scorer

## purpose
Write, freeze and execute an experiment scorer whose behavior is fixed before any treatment outcome is inspected, and run it exactly once.

## applies_when
- a gate has just been frozen and its scorer must be written
- both arms are complete and the single scoring run is next
- a flaw is discovered in a scorer that has already run

## does_not_apply_when
- the gate is not frozen yet (use experiment-preregistration)
- ad-hoc descriptive inspection scripts in the scratchpad that never produce gate verdicts
- CI verification of existing scorer outputs (use ci-offload; CI never executes scorers)

## required_inputs
- the frozen gate file and sha256
- the previous frozen scorer(s) to import, with their logged sha256
- frozen control rows (the only outcome data allowed in a dry check)

## preconditions
- the gate is frozen and logged
- no drift or treatment rows for this gate exist
- imported scorers still match their logged sha256

## procedure
1. Create `benchmark/scoring/<gate>_v1.py`; import shared metric definitions from the previous frozen scorer through a sha256-verified loader (raise if the hash differs); do not redefine shared metrics.
2. Implement only what the gate adds: arm selection by condition, split and gate sha256; each V, MI, S, C clause as one computed field; the classification exactly as the gate orders it.
3. Keep gated fields and descriptive fields in separate structures; descriptive fields never feed the verdict.
4. Pair structures positionally and raise on any pairing or replay violation; never fall back silently.
5. Dry-check on the frozen control arm only: import the module and call the arm function without `main`, confirm the control reproduces the registered values, and confirm no output file was written.
6. Exercise the classification with synthetic arm fields (one case per class and per failing clause) and the bookkeeping checks with synthetic records.
7. Compute the scorer sha256 and log it in EXPERIMENT_LOG.md ("implementation and frozen scorer" section) with the dry-check results; update `benchmark/FROZEN_MANIFEST.json` with `python scripts/verify_frozen_artifacts.py --write-manifest`; commit and push.
8. After the runs, recompute the gate and scorer sha256; if both equal the logged values, run the scorer once, saving stdout to `benchmark/results/<gate>_scorer_stdout.txt`.
9. If a flaw is found after the run, do not edit or rerun the scorer: document the flawed field, why it is wrong, whether it affects the verdict, and the corrected descriptive value derived from raw traces.

## invariants
- A frozen scorer is never silently changed or rerun outside its protocol.
- A scorer change after results exist is a new scorer file with its own logged hash.
- Dry checks never touch drift or treatment rows of the same gate.
- The verdict uses only gated fields.

## acceptance_criteria
- Scorer sha256 logged before any run; imported scorer hashes verified at runtime.
- The dry check reproduces the registered control values; synthetic cases cover every class.
- Exactly one scoring run, with stdout and the frozen JSON output committed.
- Any post-run flaw is documented in the analysis section, not patched.

## evidence_to_record
- scorer path and sha256, imported scorer hashes
- dry-check values vs registered control values
- synthetic class checks and their results
- the stdout file and frozen JSON output paths

## failure_modes
- a descriptive field mislabels behavior (EXP-20 `next_action` reported `none` for `done`): document, do not patch
- a descriptive field under-counts (EXP-21 `blocked_after_earlier_successful_edit`): document the corrected value from traces
- the dry check accidentally runs `main` and writes an output file before runs exist: delete nothing silently; report it
- the classification order differs from the gate: caught by synthetic class checks

## related_CAP_CON_METH_records
- METH-003
- METH-006
- METH-010
