# Gate diagnose_v1 — diagnosis before mutation, with complete file views held fixed

Pre-registered 2026-09-14, before any run of these conditions. Not to be edited after the first run. A revision is a new file (`diagnose_v2.md`) and reruns every condition.

## Question
With evidence availability held constant and complete, does forcing a diagnosis before mutating an existing file improve repair performance?

## Historical validity
- The earlier L1 end-to-end results (`e2e_l1_v1`) remain valid measurements of the old system.
- They cannot establish performance under adequate evidence exposure: compact reads showed the model at most 200 characters (`SchemaRouter._PREVIEW_LIMIT`), which hid the defect in some gold files.

## Conditions (dev split, 20 tasks: 16 solvable + 4 insufficient-evidence; temperature 0; sequential; model unloaded between conditions)
| condition | overrides beyond the shared `HARNESS_POLICY` + constrained text protocol |
|---|---|
| `{gemma,qwen}_fullread` (control) | `targeted_grounding: True`, `full_read_views: True` |
| `{gemma,qwen}_diagnose` (intervention) | control + `diagnose_before_mutation: True` |

Frozen across the two arms: corpus, task prompts, model and digest, temperature, guards, retry policy, context limits, verifier (lane), oracle, scoring, this gate. The intervention necessarily adds exactly one logical tool (`diagnose`) to the schema and one guidance paragraph. Nothing else in the prompt differs.

Grounding (L1) is on in both arms, held constant. It is not the factor under test. Without it Gemma first touched a gold file on 0/16 tasks, so the diagnosis mechanism would rarely get a chance to act.

`full_read_views` is an experimental control, not a production decision. The production read strategy (ranged or chunked, evidence-preserving) is a separate design.

## Mechanism (`diagnose_before_mutation`)
- New action `diagnose` with args `path`, `evidence`, `cause`, `change`, all required strings.
- `diagnose` succeeds only if `path` is an existing workspace file and `evidence` appears verbatim in its current contents. Whitespace runs are collapsed on both sides and at least 5 non-space characters are required. Otherwise it is a tool failure, handled by the normal failure/repeat policy.
- Guard: `write_file` / `replace_text` / `patch_json` on an EXISTING file is refused (`PolicyRejection`, reason `diagnosis_required`) unless a successful `diagnose` for that exact path happened earlier in the run. One diagnosis per path per run. New files are unaffected.
- Nothing checks that the edit matches the diagnosis (no binding in v1).

## Validity invariant
- Every successful read of a seeded file must deliver the complete file (`read_views[].complete` is not False).
- A solvable row with any `complete == False` read is INVALID and excluded from the gate.
- If either arm of a model has more than 2 invalid solvable rows, that model's gate is INCONCLUSIVE.

## Gate, per model, `_diagnose` vs `_fullread`
- Primary: `oracle_passed_solvable` (valid rows) rises by >= 3 tasks. 1–2 = noise.
- Must not regress:
  - `lane_false_verified` stays 0
  - `false_completion_on_insufficient_evidence` does not rise
  - `damaged_file_tasks` does not rise
- PASS only if the primary criterion and all three must-not-regress criteria hold. A near miss is FAIL.

## Reported, not decisive
- Evidence coverage = `gold_shown_complete`: every gold file received as a complete view at least once. "Read the file" (read_recall) is no longer counted as coverage.
- Diagnosis rate, diagnosis defect-hit rate, `diagnosis_required` rejections, mutation precision, gold edit recall, model false done claims, escalations, rounds, prompt tokens.

Failure split for solvable rows that fail the oracle (intervention arm; control arm reports only the first two):
- `no_gold_view`: some gold file was never shown completely (evidence not available; not a semantic failure).
- `gold_viewed_no_diagnosis_hit` (misunderstood): no successful diagnosis whose evidence lies in a gold file's defect region.
- `wrong_edit_choice`: a diagnosis hit the defect, and every gold file the run changed ends valid (not in `damaged_files`, Python compiles / JSON parses), yet the oracle fails.
- `mechanical_failure`: a diagnosis hit the defect, but no successful mutation of a gold file happened, or a changed gold file ends damaged or invalid.

Defect region is computed by the evaluator from the reference patch, independent of the loop: seed-file lines inside non-equal difflib opcodes between the seed and the reference text; for pure insertions, the line before and the line at the insertion point. A diagnosis hits when the seed lines matched by its evidence intersect that region widened by ±1 line.

## After the gate
- PASS → follow-up 2×2 (200-char vs full reads × current vs diagnose) to measure the read-completeness effect and the interaction.
- FAIL → the failure split localizes the weakness with truncation eliminated as an explanation. No 2×2.
- Heldout split is not used for this gate.
