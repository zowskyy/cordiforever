---
id: experiment-execution
version: 2
---

# Skill: experiment-execution

## purpose
Run the arms of a pre-registered experiment locally without changing its semantics, so every row is attributable to the frozen gate, while using a measured, evidence-based execution envelope (a resident model shared by independent sequential tasks) instead of a blanket one-task-per-call rule.

## applies_when
- a gate is frozen, its mechanism and scorer are committed, and model runs are about to start or resume
- a run was interrupted (timeout, memory kill, process failure) and must continue
- choosing the foreground batch size for sequential task execution

## does_not_apply_when
- the gate is not yet frozen (use experiment-preregistration)
- the runs are complete and scoring or closure is next (use frozen-scorer and research-closure)
- the work would run inference in CI (not allowed; see ci-offload)
- benchmarking concurrency or new batch sizes (a separate execution benchmark, never inside a running experiment)

## required_inputs
- gate path and its logged sha256
- condition names for drift and treatment in `benchmark/repo_task_eval.py`
- split (dev or heldout) named in the gate
- the commit containing mechanism, tests and scorer, with CI status
- the authorized maximum foreground batch size for this machine and experiment (recorded in DECISIONS)
- equivalence evidence that model residency does not change model-visible behavior (recorded in EXPERIMENT_LOG)

## preconditions
- `git status` is clean for harness sources, and the registration commit is pushed
- the gate file sha256 equals the value logged in EXPERIMENT_LOG.md
- the scorer sha256 equals its logged value (the scorer is written before any run)
- `CONDITIONS[<treatment>]["overrides"]` equals control overrides plus exactly the registered key
- Ollama is running with the registered model; no other model is loaded (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`)
- no result rows exist for the gate before the first arm starts (or only valid completed rows when resuming)

## procedure
1. Recompute the gate and scorer sha256; if either differs from the logged value, stop and report.
2. Check the condition overrides in `benchmark/repo_task_eval.py` against the gate's arm definitions.
3. Default to sequential execution on memory-constrained hardware. Run the drift arm first as foreground invocations of at most the authorized batch size: `.venv\Scripts\python.exe benchmark\repo_task_eval.py --condition <control-condition> --split <split> --gate <gate> --max-new <batch>`. Multiple independent tasks in one invocation keep the model resident; each task still gets a fresh application, conversation/message context, workspace and evaluation state from `run_task`.
4. After each invocation, run a read-only resource and provenance guard: process exit status, Ollama/model health (`/api/ps`), completed-row count for the gate, duplicate fingerprints, harness sha256, required row fields, available memory from the residency log, and per-task latency (row `seconds`) against the measured envelope. Do not inspect outcomes.
5. Confirm each invocation's rows are durable (fsync'd JSONL) before starting the next invocation.
6. On memory pressure, swapping, abnormal latency, Ollama instability or process failure, reduce the batch size immediately (for example to 2, then 1); this is an operational response, not an experimental change.
7. If an invocation fails or times out, do not rerun durable completed tasks: resume with the same condition, split and gate; the runner skips completed fingerprints. Log the event as transient infrastructure, separate from model outcomes.
8. When the drift arm is complete, run the gate's drift validity checks that are computable without treatment rows (via the frozen scorer's functions, without its `main`); if drift fails validity, stop and do not run the treatment arm.
9. Run the treatment arm the same way; do not inspect partial treatment outcomes.
10. When both arms are complete, verify that all rows share one harness sha256, that the results files are append-only (the new file starts with the committed bytes), that there are no duplicate fingerprints, and that counts match the gate.
11. Hand off to frozen-scorer; do not look at pass or fail numbers before the single scorer run.

## invariants
- Execution follows the frozen gate exactly: no condition, split, prompt, max-rounds, corpus, model parameter, context length, quantization, sampling or evaluation change for throughput.
- Sequential tasks may share a resident model process/cache for computational efficiency only when every task still receives an independent application state, conversation/message context, workspace, evaluation state and durable result record, and equivalence evidence shows residency does not change model-visible behavior.
- Model residency never permits information or mutable task state to cross task boundaries: no task result, message, tool state or workspace mutation becomes input to another task.
- Each completed task is checkpointed durably before the next task begins; resume skips already-valid completed fingerprints; a failed invocation never causes durable completed tasks to be rerun.
- Batch size is an operational resource limit, not an experimental variable, provided equivalence has been established; it never exceeds the authorized maximum during an experiment.
- No concurrent model workers unless separately benchmarked and approved.
- Execution stays in the foreground; long batches are never moved into an uncontrolled background process to bypass an execution timeout.
- Results files are append-only; no row is deleted, edited or selectively rerun; no outcome-based reruns.
- Control, drift and treatment rows stay separated by condition and gate sha256.

## acceptance_criteria
- Each arm has exactly the registered number of rows carrying the gate sha256, with no duplicate fingerprints.
- Treatment and drift rows share one harness sha256 and carry any gate-required fields.
- The append-only check passes for `benchmark/results/repo_task_eval.jsonl` and the residency log.
- Every invocation stayed within the authorized batch size and passed the resource guard, or the reduction is recorded.
- Transient failures are recorded separately from model outcomes.

## evidence_to_record
- harness sha256, model digest, row counts per arm
- batch sizes used per invocation and any reductions with their trigger
- resource guard results (available memory, latency, Ollama health)
- transient infrastructure events (timeouts, memory kills, warnings such as port binds) and how the run resumed
- the append-only check result (old and new line counts)

## failure_modes
- moving a timed-out foreground batch into the background: an uncontrolled process is memory-killed (EXP-20); resume from checkpoints in the foreground with a smaller batch
- peeking at pass counts mid-run and then changing something: invalidates the experiment
- a harness source edited after registration: the harness hash splits; stop and report
- a stray or second model loaded: memory pressure; stop and check before continuing
- concurrent workers or `OLLAMA_NUM_PARALLEL` > 1: changes batching and memory; not allowed without a separate benchmark
- a host-side warning (e.g. port 3080 bind in a second in-process application): record descriptively; stop if it ever affects task behavior rather than patching a frozen harness

## related_CAP_CON_METH_records
- METH-004
- METH-007
- METH-010
