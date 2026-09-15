---
id: experiment-execution
version: 1
---

# Skill: experiment-execution

## purpose
Run the arms of a pre-registered experiment locally without changing its semantics, so every row is attributable to the frozen gate.

## applies_when
- a gate is frozen, its mechanism and scorer are committed, and model runs are about to start or resume
- a run was interrupted (timeout, memory kill) and must continue

## does_not_apply_when
- the gate is not yet frozen (use experiment-preregistration)
- the runs are complete and scoring or closure is next (use frozen-scorer and research-closure)
- the work would run inference in CI (not allowed; see ci-offload)

## required_inputs
- gate path and its logged sha256
- condition names for drift and treatment in `benchmark/repo_task_eval.py`
- split (dev or heldout) named in the gate
- the commit containing mechanism, tests and scorer, with CI status

## preconditions
- `git status` is clean for harness sources, and the registration commit is pushed
- the gate file sha256 equals the value logged in EXPERIMENT_LOG.md
- the scorer sha256 equals its logged value (the scorer is written before any run)
- `CONDITIONS[<treatment>]["overrides"]` equals control overrides plus exactly the registered key
- Ollama is running with the registered model; no other model process is loaded

## procedure
1. Recompute the gate and scorer sha256; if either differs from the logged value, stop and report.
2. Check the condition overrides in `benchmark/repo_task_eval.py` against the gate's arm definitions.
3. Run the drift arm first, one task per call in the foreground: `.venv\Scripts\python.exe benchmark\repo_task_eval.py --condition <control-condition> --split <split> --gate <gate> --max-new 1`.
4. After each call, check row counts and provenance with a read-only script (condition, gate sha256, harness sha256, presence of required row fields); do not inspect outcomes.
5. Repeat until the drift arm has the registered row count, then run the treatment arm the same way.
6. If a call times out or is killed for memory, confirm that completed rows were kept (checkpointed JSONL), log it as a transient infrastructure event, and resume with the same command; never change the command or the arm.
7. When both arms are complete, verify that all rows share one harness sha256, that the results files are append-only (the new file starts with the committed bytes), and that counts match the gate.
8. Hand off to frozen-scorer; do not look at pass or fail numbers before the single scorer run.

## invariants
- Execution follows the frozen gate exactly: no condition, split, prompt, max-rounds or corpus change mid-experiment.
- Results files are append-only; no row is deleted, edited or selectively rerun.
- No outcome-based reruns; a rerun happens only for missing rows.
- Control, drift and treatment rows stay separated by condition and gate sha256.
- Background batches are not used on the 5.3 GB machine; one task per call.

## acceptance_criteria
- Each arm has exactly the registered number of rows carrying the gate sha256.
- Treatment and drift rows share one harness sha256 and carry any gate-required fields.
- The append-only check passes for `benchmark/results/repo_task_eval.jsonl` and the residency log.
- Transient failures are recorded separately from model outcomes.

## evidence_to_record
- harness sha256, model digest, row counts per arm
- transient infrastructure events (timeouts, memory kills) and how the run resumed
- the append-only check result (old and new line counts)

## failure_modes
- running several tasks per call in the background: memory kill and lost wall time (resume from checkpoints, one task per call)
- peeking at pass counts mid-run and then changing something: invalidates the experiment
- a harness source edited after registration: the harness hash splits; stop and report
- a stray model process causing memory pressure: stop and check before continuing

## related_CAP_CON_METH_records
- METH-004
- METH-007
- METH-010
