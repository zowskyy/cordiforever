# Gate qwen_extract_v1 — deterministic evidence extraction from the read snapshot (Qwen only)

Pre-registered 2026-09-14, before any code for the mechanism. Frozen after the first treatment run; a revision is `qwen_extract_v2.md` and reruns all arms.

## Question
Does replacing model-generated verbatim evidence with deterministic extraction from a file the model has already read in full improve defect localization, without weakening grounding, safety or verification?

## Background (fixed before this gate)
qwen_evidence_v1 repaired the ordering defect (executed pre-read diagnoses 14 → 0), but after a refusal and a full read, 7/7 re-diagnoses were still invalid. Under this interface Qwen does not reliably produce a short verbatim span from content it just read. This gate moves exact copying out of the model. It does not move localization out of the model.

## Arms (qwen2.5-coder:1.5b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control (frozen):** `qwen_evidence` rows scored by `benchmark/scoring/qwen_evidence_v1.py` (sha256 `b309c179…`) on harness `0d5b65e2ee00…`. L1 grounding, full read views, diagnose-before-mutation, read-before-evidence, model-written `evidence` quote.
- **Treatment:** `qwen_extract` = control overrides + `evidence_extraction: True`. Identical except the `diagnose` contract below.
- **Control-drift check:** the build changes the harness hash, so `qwen_evidence` is rerun on the new harness with the flag off. If its tasks-with-localized-hit differ from the frozen control by more than 1, the gate is INCONCLUSIVE.

## Model-to-extractor contract (fixed now)
- With `evidence_extraction`, `diagnose` takes `path`, `target`, `cause`, `change`. There is no `evidence` argument.
- **`target` is a constrained selector, resolved only against the read snapshot of `path`.** Exact matching only; no fuzzy, substring, prose or similarity search.
  - `.py` file: the exact name of a function, class, method (`Class.method`) or module-level assigned name defined in the snapshot (stdlib AST). Span = that definition's lines, `lineno` through `end_lineno`.
  - `.json` file: an RFC 6901 JSON Pointer (e.g. `/database/host`) that resolves in the parsed snapshot. Span = the line of the final object member's key, located by a sequential scan for each pointer segment's `"key":` in order. An array index segment maps to the line of the enclosing key.
  - Any other file type: no span.
- **Read snapshot.** The extractor reads only the exact text the model received in its most recent complete (untruncated) `read_file` result for that path during this run. Never the disk, other files, the repository index, hidden tests, oracle data or alternate copies.
  - Read-before-evidence stays on: a diagnose on a path without a complete read, or whose file changed since, is refused (`evidence_requires_read`), as in control.
- **Success result:** `Diagnosis recorded for <path> (lines a-b):` followed by the extracted lines verbatim, the cause and change, and the sha256 of the snapshot used.
- **Failure (tool error):** "`<target>` is not a function, class, method or assignment defined in <path> as you read it" or "JSON pointer `<target>` does not resolve in <path> as you read it". No suggestions, no listing of symbols or keys.
- Diagnose-before-mutation is unchanged: a successful diagnose on the path unlocks mutation.
- The guidance paragraph for `diagnose` changes only to describe `target`. Nothing else in the prompt or schema differs.

## Definitions (evaluator / scorer; fixed now)
- **Localized:** span ≤ max(3, file_lines // 4) lines (same cap as qwen_evidence_v1).
- **Localized defect hit:** a successful diagnose whose span is localized and intersects the reference-patch defect region (±1 line), computed on the seed file. The hit is computed only when the snapshot sha256 equals the seed file's sha256; otherwise it is reported as `hit_undetermined` and not counted.
- **Extraction without prior full read:** a successful treatment diagnose with no earlier complete read view of that path. Must be 0 by construction; checked from rows.

## Gate
- **Primary:** treatment tasks-with-localized-hit (solvable) ≥ 3. Control is 0/16, so this is a gain of ≥ 3.
- **Guardrails (all must hold):**
  - `lane_false_verified` = 0
  - false completion on insufficient-evidence tasks = 0/4
  - `damaged_file_tasks` ≤ control (1)
  - `stray_file_tasks` ≤ control (2) (scope)
  - leaked markers = 0 (oracle leakage)
  - extraction without prior full read = 0 (unread content)
- **Validity:** 20 rows per arm; one harness and one model digest across treatment and drift rerun; 0 invalid rows (truncated reads); drift check within 1.
- PASS only if primary, all guardrails and validity hold. INCONCLUSIVE if validity fails. FAIL otherwise.

## Reported, not decisive
Hidden-test passes; edit opportunities; localization precision (localized hits / successful diagnoses); extracted span length (lines: total, mean, max); diagnose attempts / refused pre-read / executed / successful / no-span failures by reason; `hit_undetermined` count; target kinds (py symbol / json pointer / other); prompt tokens; rounds; escalations.

## Out of scope
No quote-fidelity prompting; no repository-wide localization aid; no Gemma runs under this gate.
