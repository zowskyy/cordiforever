# Gate qwen_astnoop_v1 — structural no-op refusal for Python symbol replacements (Q-002)

Pre-registered 2026-09-15, before any code for the mechanism. DEV split only; no heldout task, row or failure pattern informs this design. Frozen after the first treatment run; a revision is `qwen_astnoop_v2.md` and reruns all arms.

## Hypothesis
Qwen sometimes satisfies the edit interface by producing a syntactically different but structurally identical replacement (dev EXP-18: `textkit_slug_punctuation` and `textkit_truncate_limit` changed only `"` to `'` on the defect line and were accepted). Refusing Python symbol replacements whose normalized AST equals the current definition forces the agent to propose a substantive edit, retry or stop, without increasing destructive edits or false verification.

## Terminology
The mechanism is a deterministic **structural no-op detector**. AST equality does not prove, and is not claimed to prove, behavioral equivalence of programs.

## Arms (qwen2.5-coder:1.5b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control (frozen, inferential):** `qwen_selectorkind` dev rows carrying gate sha256 `dcca9c02e0aee827005043ca08b4b617d4f88c7a3a048b69a975f20572f51e47` on harness `b1ee367bc339…`, scored by `benchmark/scoring/qwen_selectorkind_v1.py` (`135a71f9…`). Values: hidden-test passes 3/16, damaged 0, localized-hit tasks 8, stray 0, cumulative edit executed 6.
- **Treatment:** `qwen_astnoop` = `qwen_selectorkind` overrides + `ast_noop_refusal: True`. The only change.
- **Drift (validity only):** `qwen_selectorkind` rerun on the new harness with the flag off. Valid only if all three hold; otherwise INCONCLUSIVE. Never the inferential control.
  - hidden-test passes within 1 of 3
  - damaged-file tasks within 1 of 0
  - cumulative edit executed within 1 of 6

## Mechanism, fixed now
- **Scope:** the edit action with `selector_kind = python_symbol` only. JSON pointer edits are unchanged.
- **Rule:** the existing byte-identical rejection becomes byte-identical OR normalized-AST-identical rejection.
- **Comparison, restricted to the selected definition:**
  1. Resolve the target with the existing python_symbol selector against the file's current contents: a top-level function/class, `Class.method`, or module-level assignment.
  2. Parse the (dedented) replacement.
  3. The replacement is a structural no-op iff its module body is exactly one statement, and `ast.dump(statement, annotate_fields=True, include_attributes=False)` equals the same dump of the current target definition node.
  4. `include_attributes=False` removes line/column positions. That is the only normalization.
  5. Not added: constant folding, simplification, symbolic execution, renaming analysis, comment or docstring stripping, or any other equivalence notion. A docstring or decorator change is a structural change.
- **Refusal:** a tool error with exactly: "Replacement is structurally equivalent to the current definition and does not constitute a substantive edit." It never names a line, the expected behavior, or how to change it.
- **Unchanged:** selector resolution, evidence extraction, diagnosis, read-before-evidence, bounded-edit validation (target must be defined, no clobbering, file must compile, top-level names kept), refusal of full writes, guards, repeat and retry policy, abstention behavior, localization, grounding, prompt text, schema, decoding, max rounds, lane, oracle.

## Gate classification (exactly one)
- **Validity V:**
  - 20 rows per arm
  - one harness sha256 across treatment and drift
  - one model digest across all arms
  - treatment overrides equal control overrides + `ast_noop_refusal`
  - 0 invalid rows
  - drift within tolerance
- **Mechanism integrity MI** (required): treatment accepted structural no-op Python edits = 0. Evaluator definition: a successful `edit_symbol` python_symbol call whose replacement's single-statement dump equals the dump of the target definition in the file contents immediately before that edit, reconstructed from the seed file plus earlier successful edits in the same row.
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
  - IMPROVEMENT if passes ≥ 6 (a gain of at least +3, the program's standard beyond the 1–2 task noise band)

Classes:
1. **INCONCLUSIVE:** V fails.
2. **FAIL:** V holds and (MI fails, or S fails, or C = REGRESSION).
3. **PASS:** V, MI, S hold and C = IMPROVEMENT.
4. **PARTIAL:** V, MI, S hold and C = NO_IMPROVEMENT (mechanism works, no demonstrated completion gain).

Power note (recorded before the run): only 2 dev tasks showed the target failure, so IMPROVEMENT is unlikely even if the mechanism helps. PARTIAL is an informative outcome, not a failure of design.

## Pre-registered knowledge consequences
- **PASS:** new CAP (structural no-op refusal improves completion; dev-supported); H-012 updated.
- **PARTIAL:** new CAP at mechanism-valid (no-op refusal prevents accepted structural no-ops); CON or H update that superficial restatement is real but not the dominant completion bottleneck. The queued format-contract / semantic-reasoning questions remain next.
- **FAIL (regression or safety):** CON recording the regression; mechanism not promoted.
- **FAIL (MI):** implementation defect; the result is not interpreted as a capability finding.
- **INCONCLUSIVE:** registry only.

## Descriptive only (never gates)
- Extended funnel per solvable task: replacement proposed → parseable as the expected symbol → AST-substantive → passes existing structural guards → executed → gold intact → hidden-test pass.
- Structural no-op refusals (count, tasks); what the model did next after each refusal (same-target re-edit, other edit, diagnose, read, done, escalation); validity of the subsequent replacement.
- Accepted structural no-ops in control and drift (expected 2 in control).
- Executed edits and hidden-test pass rate among tasks with an executed gold edit.
- Outcomes on `textkit_slug_punctuation` and `textkit_truncate_limit` (the two dev restatement tasks).
- Pass-set identities; category-3 executed edits; prompt tokens; rounds; escalations.

## Out of scope
Format-contract changes; semantic reasoning aids; abstention; selector changes; heldout runs; Gemma; coordination.
