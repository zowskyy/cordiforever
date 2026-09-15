# Furthest-Reached Bottleneck Taxonomy — specification and rubric (v1)

Analysis methodology, not an experiment gate. Descriptive diagnosis over frozen dev evidence. It involves no model inference, no scorer execution and no modification of frozen evidence. This specification is hashed before any real trajectory is classified. It is not changed in response to real rows or observed label frequencies. A genuine ambiguity found during classification stops that pass for review.

Implementation: `benchmark/analysis/furthest_bottleneck.py`. Synthetic tests: `tests/test_furthest_bottleneck.py`.

## Concept
For each unsuccessful solvable trajectory, determine the furthest capability stage for which positive frozen evidence shows the trajectory satisfied the preceding requirements. Assign the trajectory to the next unresolved stage that ultimately prevented a correct solution.

- Earlier failures that are subsequently overcome are recorded as trajectory history. They do not determine the final bottleneck label.
- Example: invalid selector → later valid selector → structurally valid proposal → guard refusal → no later accepted edit. The final bottleneck is F5; the earlier F3 event remains history.

## Population and arms
- **Unit:** one task-arm trajectory: a solvable dev task (`expected_outcome == "verified_done"`) whose final hidden-test result was not a pass (`oracle_passed is not True`).
- **Primary diagnostic arm:** EXP-22 drift (`qwen_selectorkind`, gate sha256 `13e9a05b…`).
- **Identity/consistency checks only:** EXP-18 treatment and EXP-20 drift. Label disagreement with the primary arm is reported as a rubric or data defect.
- **Perturbation-stability arms:** EXP-20 treatment, EXP-21 treatment and EXP-22 treatment. Agreement is described as stability under perturbation, not replication.
- **Scope:** arms are never pooled. Heldout is excluded.

## Invariant: UNKNOWN is not FALSE
Every stage fact is tri-state: TRUE, FALSE or UNKNOWN.
- Missing, truncated or unreconstructable evidence is UNKNOWN, never FALSE.
- So is an oracle error or timeout, or any other unestablished fact.
- Missing fields, `None`, Python falsiness, exceptions and default values never produce FALSE.

Combinators:
- **Tri-AND:** FALSE if any operand is FALSE; otherwise UNKNOWN if any is UNKNOWN; otherwise TRUE.
- **Tri-ANY over a collection:** TRUE if any element is TRUE; otherwise UNKNOWN if any is UNKNOWN; otherwise FALSE.

If an UNKNOWN fact is needed to decide the bottleneck, the label is UNDETERMINED.

## Applicability facts (orthogonal to the capability stages)
The row's enabled mutation interface comes from `CONDITIONS[row.condition].overrides`, never from model behavior:
- `edit_symbol` when `localized_edits` is on
- `replace_text` and `patch_json` when `structured_edits` is on
- `write_file` overwrite of existing files when `localized_edits` is off (the loop refuses it otherwise)
- new-file creation

An unknown condition makes both applicability facts UNKNOWN.

- **D0_HARNESS (normative):** whether the enabled interface can express a repair of the required structural operation class, established conservatively from the seed files, the reference patch and the capabilities.
  - The reference patch establishes the defect and one valid solution. Its exact edit structure is not assumed to be necessary.
  - A structural operation class counts as required only when necessity is deterministic. Otherwise the fact is UNKNOWN, biasing toward UNDETERMINED rather than a false interface limitation.
- **Per gold file:**
  - **Unchanged by the reference:** TRUE.
  - **Not in the seed:** TRUE when file creation is enabled.
  - **Overwrite or `replace_text` enabled:** any textual change is TRUE.
  - **`.py` with `edit_symbol`**, classified by line diff:
    - **modify_selectable:** changed seed lines lie inside a def, async def, class (including its methods), or an Assign/AnnAssign with a Name target. TRUE.
    - **insert_top_level_statement_adjacent_to_selectable:** statements inserted next to a selectable statement (only blank or comment lines between). TRUE, because `replace_python_symbol` accepts a replacement that preserves the selected symbol and defines additional new names or statements.
    - **modify_non_selectable** (import, bare expression, other statement) or **insert_top_level_statement_without_selectable_anchor:**
      - UNKNOWN in general, since an alternative repair may not need that operation
      - FALSE only when the file contains no selectable statement at all and is the task's sole gold file
    - **remove_selectable_name:** UNKNOWN (the reference removes a name, but necessity is not established).
    - Unattributable changed lines, or unparseable seed or reference: UNKNOWN.
  - **`.json` with `edit_symbol`:** each changed location is TRUE if that location or its immediate non-root parent resolves in both documents with the same JSON kind.
    - A root replacement is FALSE for a sole gold file and UNKNOWN otherwise.
    - Any other location, or unparseable JSON: UNKNOWN.
  - **Other existing file types without overwrite or `replace_text`:** FALSE for a sole gold file, otherwise UNKNOWN.
  - **Task-level D0_HARNESS:** Tri-AND over the gold files. A gold file without a reference entry is UNKNOWN.
- **D0_CONTRACT (descriptive only; never changes a label):** the same evaluation under the single-definition replacement restriction used by the format-contract mechanism. It differs from D0_HARNESS in exactly one way: an adjacent top-level insertion is FALSE (a replacement may define only the selected symbol).
  - **Reported categories:** HARNESS TRUE / CONTRACT TRUE; HARNESS TRUE / CONTRACT FALSE (the experimental contract excludes an otherwise available repair path); HARNESS FALSE; HARNESS UNKNOWN.

## Stage facts
- **D1 defect region:**
  - For each gold file with a `reference_patch` entry and a seed text: `defect_lines(seed, reference)` widened by ±1 line (the evaluator's `hits_defect` convention).
  - A gold file without a patch entry or seed text: UNKNOWN.
- **D2 relevant target set (per gold file):**
  - **`.py`:** the union of two sets:
    - the qualified names (top-level def, async def, class; `Class.method`; module-level Assign/AnnAssign names) whose seed line span intersects the D1 region
    - **reference-added names**, defined in the reference but not in the seed
    - Empty union or unparseable seed: UNKNOWN.
    - A reference-added name counts as relevant intent even though it cannot yet be selected. With D0_HARNESS TRUE, a proposal targeting it reaches F3 (the selector cannot resolve), not F1: knowing what must change is separated from expressing it through a resolvable selector.
  - **`.json`:** the changed locations between the seed document and the reference document.
    - For dictionaries, recurse into common keys; an added or removed key is a changed location at that key.
    - For arrays of different length, the array itself is the changed location; for equal length, recurse by index.
    - For scalars and type changes, the location itself.
    - No change or unparseable documents: UNKNOWN.
- **D3 sufficient evidence:**
  - TRUE if every gold file with a D1 region has a `read_views` entry with `complete is True` whose round is no later than the first diagnosis or edit proposal on that file.
  - FALSE if some such file has no read view at all, or only views with `complete is False`, before that point.
  - UNKNOWN otherwise, including `complete is None`.
- **D4 usable diagnosis:** a `diagnoses` record on a gold file with `success is True`, `refused is None` and `target is not None`. Tri-ANY over records; a record missing any of these fields is UNKNOWN.
- **D5 correct localization:** Tri-ANY over usable diagnoses of `hits_defect is True`. A usable record with `snapshot_matches_seed is False`, or with `hits_defect` absent, contributes UNKNOWN.
- **D6 edit proposal:** each `edit_symbol` call on a gold file, taken from `edit_proposals` when present, otherwise from `calls[].args`.
  - Successful or refused `write_file`, `replace_text` and `patch_json` calls are recorded as non-primitive attempts (with the operation) and are not edit proposals.
- **D7 relevant intent:**
  - **`.py`:** the target is normalized by stripping a leading `/`, a leading `async def `, `def ` or `class `, anything from the first `(`, and whitespace.
    - TRUE if it equals a D2 qualified name, or its last dotted component equals the last component of a D2 qualified name; otherwise FALSE.
    - UNKNOWN if D2 is UNKNOWN or the target is not a string.
  - **`.json`:** structural relevance for pointer `t` against changed locations `c`, both as segment lists.
    - TRUE if `t == c`, if `t` is inside `c` (a descendant of a changed or replaced subtree), or if `t` is the immediate parent container of `c` (exactly one segment above).
    - FALSE for a root (`""` or `"/"`) or over-broad target (two or more segments above every `c`), and for unrelated locations.
    - UNKNOWN if D2 is UNKNOWN or the target is not a string.
- **D8 selector resolves:** the frozen EXP-22 classifier (`benchmark/scoring/qwen_formatcontract_v1.py`, imported after sha256 verification) runs against the file state before the proposal. SELECTOR_FAILURE is FALSE; UNCLASSIFIABLE, or an unknown pre-proposal state, is UNKNOWN; any other terminal is TRUE.
- **D9 structurally valid:** VALID is TRUE; FORMAT_INVALID or SELECTOR_FAILURE is FALSE; UNCLASSIFIABLE or an unknown pre-proposal state is UNKNOWN.
- **D10 accepted:** `success is True` is TRUE; `success is False` is FALSE; absent is UNKNOWN.
- **D11 correct repair at state k:**
  - State k is the seed workspace plus the complete ordered sequence of successful mutations (any tool) up to and including mutation k.
  - Each is reconstructed from `edit_proposals.after_text`, or by replaying untruncated arguments with the harness edit functions (`edit_symbol`, `replace_text`, `patch_json`) or the full `write_file` content.
  - The existing independent `run_oracle` runs on a temporary copy. A pass is TRUE; a fail is FALSE.
  - Any preceding successful mutation that cannot be faithfully reconstructed, a truncated argument, an oracle error or timeout, or an oracle not applicable: UNKNOWN.
- **D12 post-mutation regression evidence:** after the latest state k with D11 TRUE, TRUE if a later successful mutation changed a gold file, or a gold file appears in `damaged_files` or `invalid_gold_files`; otherwise FALSE.

A proposal's chain is Tri-AND of D7, D8, D9 and D10 up to the stage considered. The reach facts are Tri-ANY over proposals:
- R7 = ANY(D7)
- R8 = ANY(D7 ∧ D8)
- R9 = ANY(D7 ∧ D8 ∧ D9)
- R10 = ANY(D7 ∧ D8 ∧ D9 ∧ D10)

## Bottleneck labels (evaluated from the furthest stage; exactly one)
0. **D0_HARNESS FALSE** → **INTERFACE_UNSUPPORTED**. Not F0–F8, not a model-capability failure, excluded from the F0–F8 denominator, and reported separately (raw count and task IDs), including in the intervention-opportunity analysis. **D0_HARNESS UNKNOWN** → **UNDETERMINED**. D0_CONTRACT is never consulted.
1. **UNDETERMINED** if D1 or D2 is UNKNOWN for the task.
2. **If R10 is TRUE:** let C = ANY over successful mutation states k of D11(k).
   - C TRUE, final state D11 TRUE → **F8 verification/other**.
   - C TRUE, final state D11 UNKNOWN → **UNDETERMINED**.
   - C TRUE, final state D11 FALSE: D12 TRUE → **F7 post-mutation trajectory**; D12 FALSE → **UNDETERMINED** (no positive regression evidence).
   - C UNKNOWN → **UNDETERMINED**.
   - C FALSE → **F6 replacement content**.
3. **R10 UNKNOWN** → **UNDETERMINED**.
4. **R9 TRUE** → **F5 execution-guard rejection**; R9 UNKNOWN → **UNDETERMINED**.
5. **R8 TRUE** → **F4 replacement structure/format**; R8 UNKNOWN → **UNDETERMINED**.
6. **R7 TRUE** → **F3 selector representation**; R7 UNKNOWN → **UNDETERMINED**.
7. **No relevant proposal (R7 FALSE):**
   - D5 TRUE: if a gold-file edit proposal exists → **F1 localization/diagnosis** (sub-label edit_targets_wrong_location); otherwise → **F2 action initiation**.
   - D5 UNKNOWN → **UNDETERMINED**.
   - D5 FALSE, gold-file edit proposals exist → **F1** (edit_targets_wrong_location).
   - D5 FALSE, D4 TRUE → **F1** (diagnosis_misses_defect).
   - D5 FALSE, D4 FALSE, D3 FALSE → **F0 evidence acquisition**.
   - D5 FALSE, D4 FALSE, D3 TRUE → **F1**, with sub-label no_diagnosis_attempted (no diagnose call on a gold file), diagnosis_attempted_unusable, or diagnosis_attempt_unknown.
   - D5 FALSE, D4 or D3 UNKNOWN → **UNDETERMINED**.

F0 is assigned only when missing evidence precedes and plausibly blocks what follows (no usable diagnosis and no relevant edit). A trajectory that localized without a complete read is not F0.

## Descriptive sub-labels (never change the bottleneck)
- **History:** for each proposal, the stage at which its own chain stopped, plus non-primitive attempts in order.
- **F1:** edit_targets_wrong_location, diagnosis_misses_defect, diagnosis_attempted_unusable, no_diagnosis_attempted (diagnosis_attempt_unknown when the call record cannot establish it).
- **F2**, first match:
  - non_primitive_mutation_attempt_only (with operations)
  - escalation:<reason> (`agent_escalation` present)
  - premature_done (`model_claimed_done is True`)
  - stall_or_max_rounds (`rounds >= 12`)
  - other
- **F5 guard reason:** from the refused proposal's result head.
  - reason keys: structural_noop (the EXP-20 refusal text), then the frozen `EDIT_FAILURE_REASONS` keys from `benchmark/scoring/qwen_selectorkind_v1.py`, then precondition (named file not read / diagnose required / already exists), then blocked_repeat, else other_guard
  - **guard judgement (counterfactual about the proposal; never a normative judgement of the guard policy):** the refused proposal is applied without guards to its pre-state (Python: the replacement re-indented into the target's span in that state; JSON: the value set at the pointer), then `run_oracle` runs
    - oracle FALSE, or the file no longer compiles or parses → `A_protective_against_proposal`
    - oracle TRUE → `B_counterfactually_successful_if_applied`
    - UNKNOWN or not appliable → `C_undetermined`
    - A guard can enforce a valid safety or evidence invariant while refusing a mutation that would counterfactually pass the hidden tests, so B does not establish that the guard was wrong.
- **F6 content subtype** (descriptive and secondary), from pre- and post-edit target definitions of the accepted relevant proposals:
  - If the definitions are AST-equal → cosmetic_restatement (exclusive).
  - Otherwise the dimension set S collects:
    - signature (name, arguments, decorators or returns changed)
    - algorithm (statement-structure shape changed)
    - condition_value_formula (same statement structure, differences only in expressions)
    - incomplete_repair (oracle detail reports at least one passed and at least one failed hidden test for the final accepted state)
  - Expression differences in more than one statement, or dimensions under S from several accepted edits that disagree, → MULTIPLE.
  - |S| = 1 → that subtype; |S| > 1 → MULTIPLE; |S| = 0 → OTHER.
  - JSON edits → OTHER. Anything not computable → UNDETERMINED_SUBTYPE.

## Reproducible mutation checks
- `benchmark/analysis/furthest_bottleneck_mutations.py` holds each mutation's exact anchor, replacement and expected status (caught, or equivalent with the caught mutation that proves the protected property).
- It also holds the namespace-package loader, which imports `benchmark.analysis` first and sets the child attribute.
- Full run (manual): `python benchmark/analysis/furthest_bottleneck_mutations.py`.
- Fast structural checks run in `tests/test_furthest_bottleneck_mutations.py`.

## Oracle-replay safeguards
- The existing `benchmark.repo_task_eval.run_oracle` is used unchanged, on temporary copies of the seed repository.
- Frozen rows are read only.
- No scorer's `main` is run.
- No model is contacted.
- Oracle errors and timeouts are UNKNOWN.
- Nothing is written under `benchmark/results`, `benchmark/gates`, `benchmark/scoring`, `benchmark/repos` or `benchmark/oracle`.

## Analysis outputs (after approval of classification; descriptive only)
1. Primary-arm bottleneck counts, with percentages and raw denominators. INTERFACE_UNSUPPORTED is excluded from the F0–F8 denominator and reported separately (count and task IDs), together with the four D0_HARNESS/D0_CONTRACT categories.
2. Identity-arm label agreement.
3. Perturbation-arm counts and per-task agreement.
4. UNDETERMINED counts.
5. F5 reasons and A/B/C judgements.
6. F6 subtypes.
7. Per-arm funnel D3 → D5 → R7 → R8 → R9 → R10 → any D11.
8. A separate intervention-opportunity assessment (frequency, stability, causal proximity, isolability, damage or false-verification risk, deterministic solvability) that designs no experiment.
