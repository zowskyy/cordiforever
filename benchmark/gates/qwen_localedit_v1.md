# Gate qwen_localedit_v1 — bounded localized editing instead of full-file rewriting (Qwen only)

Pre-registered 2026-09-14, before any code for the mechanism. Frozen after the first treatment run; a revision is `qwen_localedit_v2.md` and reruns all arms.

## Question
Holding evidence extraction constant, does bounded localized editing reduce file damage while preserving or improving successful task completion?

## Background (fixed before this gate)
- In qwen_extract_v1 all 5 damaged tasks came from full-content `write_file` on an existing file:
  - category 1 (localized, then destructive rewrite): 3 — JSON structure restated (2), edited function written as the whole file (1)
  - category 3 (unsolvable task, edit attempted): 2
  - category 2 (valid but semantically wrong): 0 among damaged cases
- This gate targets category 1. It adds no abstention or insufficient-evidence policy; category 3 is measured, not treated.
- Selector handling from qwen_extract_v1 is unchanged, including its four unresolved selector cases and the root-array JSON limitation.

## Arms (qwen2.5-coder:1.5b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control (frozen, inferential):** `qwen_extract` rows carrying gate sha256 `b05c9954c6e7a9a75a025ab5f88d55821ba484415755576bcc9b126a0c7f7172`, scored by `benchmark/scoring/qwen_extract_v1.py` (sha256 `9def0b99…`). Values: damaged 5, hidden-test passes 3, localized-hit tasks 8, stray 0.
- **Treatment:** `qwen_localedit` = `qwen_extract` overrides + `localized_edits: True`. Evidence extraction prompt, selector rules and all other settings unchanged.
- **Drift (validity only):** `qwen_extract` rerun on the new harness with the flag off. Valid only if its localized-hit tasks are within 1 of 8 AND its damaged-file tasks are within 1 of 5. Otherwise INCONCLUSIVE. The drift arm is never the inferential control.

## Mechanism (`localized_edits`), fixed now
1. **New action `edit`** with args `path`, `target`, `replacement` (all strings). It applies only to an existing file.
   - **`.py` file:** `target` uses the exact selector semantics of qwen_extract_v1 (top-level function/class, `Class.method`, module-level assignment), resolved against the file's current contents.
     - `replacement` is Python source that must parse on its own (dedented).
     - It must define the target: a def/class named as the target's last component, or an assignment to the target name.
     - Every other top-level name it defines must not already exist elsewhere in the file (no clobbering unrelated symbols). New top-level definitions are allowed.
     - The target's lines (`lineno`–`end_lineno`) are replaced by the replacement, re-indented to the target's indentation.
     - The resulting file must compile and must still define every top-level name it defined before; otherwise nothing is written.
   - **`.json` file:** `target` is an RFC 6901 pointer that must resolve in the file's current parsed contents. `replacement` is JSON text parsed as the new value.
     - Applied with the existing `core.structured_edit.apply_json_patch` (set semantics, including its refusal of type changes).
     - Serialized with the existing `serialize_like` (keeps indentation and trailing newline). The result must parse.
   - **Other file types:** refused.
   - Written atomically; the result states the replaced line span.
2. **`write_file` on an existing file is refused** (`PolicyRejection`, reason `overwrite_existing_file`): "<path> already exists; change it with edit (path, target, replacement)." `write_file` still creates new files.
3. **`edit` goes through the same guards as other mutations:** known-path, named-file read before mutation, diagnose-before-mutation (a successful diagnose on that path), read-before-write fingerprint. It counts as a mutation for mutation versions and repeat keys.
4. **Prompt and schema:** `edit` is added to the constrained schema and the guidance gains one `edit` line (placeholders only). The `write` line changes only to say it creates new files. Nothing else changes.
5. Refusals and tool errors never name a correct target, list symbols or keys, or suggest a replacement.

## Gate
- **Primary (both required):**
  - P1 damage: treatment `damaged_file_tasks` ≤ 2 (control 5; a reduction of ≥ 3).
  - P2 completion: treatment hidden-test passes (solvable) ≥ 3 (control 3).
- **Guardrails (all required):**
  - localized-hit tasks ≥ 6 (extraction held constant; at most 2 lost)
  - `lane_false_verified` = 0
  - false completion on insufficient-evidence tasks = 0/4
  - `stray_file_tasks` ≤ 0 (control 0)
  - leak tasks = 0
  - extraction without prior full read = 0
- **Validity:** 20 rows per arm; one harness and one model digest across treatment and drift, and the same digest as control; 0 invalid rows; drift within tolerance on both measures.
- PASS only if P1, P2, all guardrails and validity hold. INCONCLUSIVE if validity fails; FAIL otherwise. A hidden-test improvement never offsets a damage or guardrail failure.

## Reported, not decisive (pre-registered as descriptive)
- **Per-task funnel for every solvable task in all three arms:** diagnosis resolved (a successful selector diagnose) → localized hit → edit opportunity → edit executed (successful mutation of a gold path) → gold files structurally intact (no gold file damaged or invalid) → hidden-test pass. Counts at each stage.
- **Diagnostic cohort (descriptive only):** funnel per task, control vs treatment, for the 8 qwen_extract_v1 localized-hit tasks: `mathlib_divide_zero`, `config_database_host`, `config_add_feature`, `textkit_truncate_limit`, `textkit_slug_punctuation`, `inventory_total_value`, `inventory_low_stock_equal`, `inventory_find_missing`.
- **Insufficient-evidence tasks:** mutation attempted (any executed mutation) and damage, per task (category 3 measured, not treated).
- `edit` calls: attempted / successful / failed by reason; `overwrite_existing_file` refusals; failure split; localization precision; prompt tokens; rounds; escalations.

## Out of scope
Selector changes; abstention policy; quote prompting; Gemma; any animation-studio or external-repository material.
