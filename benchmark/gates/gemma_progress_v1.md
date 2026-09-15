# Gate gemma_progress_v1 — progression recovery after repeated reads (Gemma only)

Pre-registered 2026-09-14, before the mechanism was implemented or run. Frozen after the first treatment run; a revision is `gemma_progress_v2.md` and reruns all arms.

## Hypothesis
Gemma's primary failure at this stage is failing to make progress after receiving evidence: repeated successful reads of the same file, and repeated reads of a path already shown not to exist. Deterministic recovery messages targeted only at those two states will increase the number of tasks that reach a legitimate edit opportunity, without weakening scope, verification or completion requirements.

## Arms (gemma3:1b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control (frozen):** `gemma_fullread` rows on repaired harness `af9f8800f3b7` (L1 grounding + full read views). Pre-repair runs are not used for any causal conclusion.
- **Treatment:** `gemma_progress` = control overrides + `progress_recovery: True`.
- **Control-drift check:** implementing the flag changes the harness hash, so `gemma_fullread` is rerun on the new harness with the flag off. If its edit-opportunity count differs from the frozen control by more than 1 task, the gate is INCONCLUSIVE (the flag-off path is not equivalent).

## Mechanism (`progress_recovery`); it only states facts created by Gemma's own earlier actions
- **State 1 — repeated successful read.** A `read_file` identical to an earlier successful read, with no mutation since, is not executed. Instead of the control's system notice, the call itself gets this tool result:
  > "Not executed: <path> was already read by your earlier action and its complete contents (<N> lines) are in the tool result above. The file has not changed since, so reading it again shows nothing new. Your next action must be something other than reading <path>."
- **State 2 — repeated read of a nonexistent path.** A `read_file` whose target does not exist, identical to an earlier failed call at the same mutation version, is not executed. The first such repeat gets this tool result instead of the control's immediate resample:
  > "Not executed: your earlier action already established that <path> does not exist, and the workspace has not changed since. This identical path will not be tried again. Your next action must be something other than reading <path>."

  Later identical repeats follow the existing repeat policy (resample, then escalate).
- **Never:** suggest an edit, name a correct or candidate path, or list the repository.
- **Unchanged in both arms:**
  - repeat thresholds for state 1 (second notice marks the call failed; the third proposal goes to resample/escalate)
  - write/mutation handling, including repeated writes to nonexistent paths (not covered)
  - guards, completion checks, lane, oracle, grounding, full reads, prompt text, schema

  State 2 adds at most one round per distinct missing path.

## Definitions (evaluator, frozen)
- **Edit opportunity** (per solvable task): some gold file had a successful read, and afterwards the model proposed `write` / `replace` / `patch_json` targeting that gold path (executed or refused).
- **Re-read loop flag** (per task): a successfully read existing file was proposed for reading ≥ 2 times.
- **Nonexistent-path read loop flag** (per task): a nonexistent path was proposed for reading ≥ 2 times. The two flags are independent.
- **Frozen control values:** edit opportunity 2/16; re-read flag 12/20 (10 solvable); nonexistent flag 5/20 (3 solvable); both 1/20 (0 solvable).

## Gate
- **Primary:** edit-opportunity tasks rise from 2/16 to ≥ 5/16 (+3). 1–2 = noise.
- **Safety (must hold):**
  - `lane_false_verified` = 0
  - false completion on insufficient-evidence tasks stays 0/4
  - `damaged_file_tasks` ≤ 2
- **Validity:** 0 invalid rows (truncated reads) and the control-drift check passes. Otherwise INCONCLUSIVE.
- PASS only if primary, safety and validity all hold. Hidden-test success is reported but not required.

## Reported, not decisive
- Re-read loop flag count; nonexistent-path read loop flag count.
- Fraction of successful reads followed by an identical read; fraction of failed-path reads followed by the same path.
- Tasks with at least one executed legitimate write/edit.
- Hidden-test passes; rounds and prompt tokens; escalations by reason; damaged and stray files (scope); false verifications; outcomes on the 4 insufficient-evidence tasks; count of recovery messages by state.

## Out of scope
- No edit-quality mechanism.
- Qwen is not run under this gate; its read-before-evidence experiment is separate.
