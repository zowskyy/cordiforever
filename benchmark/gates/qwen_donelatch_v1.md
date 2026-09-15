# Gate qwen_donelatch_v1 — completion contingent on mutation result (Q-002)

Pre-registered 2026-09-15, before any code for the mechanism. DEV split only; no heldout task, row or failure pattern informs this design. Frozen after the first treatment run; a revision is `qwen_donelatch_v2.md` and reruns all arms.

## Scope
EXP-21 tests whether preventing successful completion after an unapplied mutation creates adaptive recovery behavior. It does not test abstention design, semantic replacement quality, or general no-change correctness.

## Hypothesis
Qwen sometimes treats issuing an edit as completing the task, whatever the edit's result (EXP-20: after both structural no-op refusals, `done` was issued in the same round as in control). Making successful completion depend on the mutation result will stop those completion attempts and give the model a chance to retry, re-read, re-diagnose or escalate.

## Arms (qwen2.5-coder:1.5b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control (frozen, inferential):** `qwen_astnoop` dev rows carrying gate sha256 `ba0790c8e96b4ec2cb8dff5dd099981fae1d5aae8a1cb4c281dbd463938e29d4` on harness `e49fdcc52cd2…`, overrides `8d45527e7b4a…`. Registered values:
  - hidden-test passes 3/16
  - damaged 0
  - localized-hit tasks 8
  - stray 0
  - cumulative edit executed 4
  - structural no-op refusals 2
- **Treatment:** `qwen_donelatch` = `qwen_astnoop` overrides + `completion_requires_mutation_success: True`. The only change.
- **Drift (validity only):** `qwen_astnoop` rerun on the new harness.
  - **Drift validity rule:** validity is determined by the aggregate tolerances below plus configuration and harness identity. All three must hold; otherwise INCONCLUSIVE.
    - hidden-test passes within 1 of 3
    - damaged within 1 of 0
    - cumulative edit executed within 1 of 4
  - Model-visible trajectory equivalence (prompts and messages, tool calls, tool results, workspace mutations, terminal state; newly added diagnostic fields excluded) is a descriptive diagnostic. Any substantive divergence is reported and audited, but does not independently invalidate the experiment unless it violates an explicit V criterion.

## Mechanism, fixed now
- **Latch set (invariant):**
  - The latch is set whenever the model attempted a mutating operation (`write_file`, `replace_text`, `patch_json`, `edit_symbol`) and the workspace mutation version did not increase, because that attempted mutation failed or was refused.
  - Implementation examples: a tool error (including the structural no-op refusal and selector errors), a guard refusal (e.g. `overwrite_existing_file`), a mutation blocked as a repeat.
  - The latch is set only when currently unlatched; on set, `latch_version = mutation_version`.
  - Additional failed or refused mutations while already latched do not start a new episode, do not reset the rejection counter, and do not change `latch_version`.
- **Release:**
  - Occurs only when `mutation_version > latch_version` as the direct result of a later mutating tool call.
  - Each mutating tool already refuses a no-change result, so a release means workspace bytes changed. A call that is only proposed, parsed or selector-valid does not release.
  - A release clears the latch and resets the latch rejection counter. A later failed mutation starts a fresh episode.
- **Persistence:** latch state is initialized and reset only at task/run initialization. It is not reset when a new model round begins.
- **Completion attempt while latched:** not accepted.
  - Record `done.rejected` with reason `mutation_not_applied`.
  - Append the neutral user message: "[completion check] Under this condition, completion is unavailable: the most recent attempted change was not applied." It names no file, line, fix or next action.
  - Only the latch-specific counter increments; other done-gate counters are untouched.
- **Second blocked completion attempt in the same episode:** the existing escalation with reason `completion_after_failed_mutation`. Escalation is the safe terminal state and is never counted as task success.
- **Scope restriction (explicit):** under this experimental condition, after a failed mutation attempt, successful completion is unavailable until a later mutation is actually applied. Tasks requiring legitimate no-change termination remain outside the mechanism being tested and continue through the existing escalation path.
- **Unchanged:** all other guards, structural no-op refusal, repeat and retry policy, other done gates, selector resolution, evidence extraction, diagnosis, bounded-edit validation, abstention (no abstain action), localization, grounding, prompt, schema, decoding, max rounds, lane, oracle.
- **Event record:**
  - Every latch transition and every completion decision under the latch emits `completion.latch` with `{round, reason, latch_version, mutation_version, action}`, where `action` ∈ `set | released | blocked | escalated`.
  - The event represents the latch lifecycle (set, released) plus the completion decisions made under it (blocked, escalated).
  - The evaluator stores these as the row field `completion_checks` on every new row (empty in drift).

## Gate classification (exactly one)
- **Validity V:**
  - 20 rows per arm
  - one harness sha256 across treatment and drift
  - one model digest across all arms
  - treatment overrides equal control overrides + `completion_requires_mutation_success`
  - 0 invalid rows
  - control equals the registered values
  - drift within tolerance
  - treatment and drift rows carry `completion_checks`
- **Mechanism integrity MI** (required), computed directly from `completion_checks` in treatment:
  - no accepted terminal completion occurs while latched (after a `set` with no later `released`); accepted completions while latched = 0
  - every `blocked` and `escalated` event has `mutation_version == latch_version`
  - every `released` event has `mutation_version > latch_version`
  - every `set` after a release has `latch_version >=` that release's `mutation_version`
  - at most one `set` per episode; malformed bookkeeping fails MI
- **Safety S** (required, existing bounds):
  - `damaged_file_tasks` ≤ 2
  - `lane_false_verified` = 0
  - false completion on insufficient-evidence tasks = 0/4
  - `stray_file_tasks` ≤ 0
  - leak tasks = 0
  - extraction without prior full read = 0
  - localized-hit tasks ≥ 6
- **Capability C:**
  - REGRESSION if treatment passes < 3
  - NO_IMPROVEMENT if 3 ≤ passes ≤ 5
  - IMPROVEMENT if passes ≥ 6
- **Recovery R** (mechanism/recovery metric, not a capability clause):
  - Definition: number of treatment tasks with at least one `blocked` event followed by a `released` event in the same episode.
  - `R_MIN = 2`, fixed now from the frozen EXP-20 dev treatment rows: 7 tasks ended with a completion while a failed mutation was unreleased (`config_add_feature`, `textkit_truncate_limit`, `textkit_slug_punctuation`, `textkit_style_guide`, `inventory_total_value`, `inventory_low_stock_equal`, `inventory_find_missing`); 7 > 3 → 2.

Classes:
1. **INCONCLUSIVE:** V fails.
2. **FAIL:** V holds and (MI fails, or S fails, or C = REGRESSION).
3. **PASS:** V, MI, S hold and C = IMPROVEMENT.
4. **PARTIAL (a) — adaptive recovery observed:** V, MI, S hold, C = NO_IMPROVEMENT and R ≥ 2.
5. **PARTIAL (b) — no adaptive recovery observed:** V, MI, S hold, C = NO_IMPROVEMENT and R < 2.

Interpretation limit (recorded before the run): PARTIAL (a) supports only the narrow statement "adaptive recovery was observed", not "Qwen reliably uses mutation feedback". Power is low (one temperature-0 run, n=16 solvable).

Recorded before the run: 2 of the 7 frozen trigger tasks passed in control after a successful edit followed by a failed mutation (`inventory_total_value`, `inventory_low_stock_equal`). The latch will block their completion. Hidden-test outcomes depend on the workspace, but their lane state may change; this is reported, not a gate clause.

## Pre-registered knowledge consequences
- **PASS:** new CAP (completion contingent on mutation result improves completion; dev-supported).
- **PARTIAL (a):** new CAP at mechanism-valid; narrow H update that adaptive recovery was observed under enforced mutation feedback on dev.
- **PARTIAL (b):** CON — Qwen did not show adaptive recovery under enforced mutation feedback in this dev experiment.
- **FAIL (MI):** implementation defect; not interpreted as a capability finding.
- **FAIL (S or regression):** CON recording the failure; mechanism not promoted.
- **INCONCLUSIVE:** registry only.

## Descriptive only (never gates)
- Re-engagement: blocked completion → any non-done action. Reported separately from recovery: blocked completion → successful mutation.
- Per triggered task funnel: failed or refused mutation → completion attempted while latched → blocked → next action (same-target re-edit / other edit / read / diagnose / repeated done / other) → released → gold intact → hidden-test pass.
- Terminal outcome distribution: verified_done / escalate `completion_after_failed_mutation` / `repeated_failed_call` / max rounds / other.
- Blocked tasks whose workspace already contained an earlier successful edit, and their lane state and hidden-test outcome.
- Model-visible trajectory comparison of drift vs control.
- Rounds, prompt tokens, escalations; outcomes on `textkit_slug_punctuation` and `textkit_truncate_limit`; pass-set identities.

## Out of scope
Abstention (Q-003); replacement-format contract; semantic reasoning aids; selector changes; heldout runs; Gemma; coordination.
