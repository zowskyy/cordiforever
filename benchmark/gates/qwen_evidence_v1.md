# Gate qwen_evidence_v1 — read-before-evidence for diagnosis (Qwen only)

Pre-registered 2026-09-14, before the mechanism was implemented or run. Frozen after the first treatment run; a revision is `qwen_evidence_v2.md` and reruns all arms.

## Hypothesis
Qwen's dominant failure at the diagnosis step is evidence discipline: it submits a diagnosis before reading the file (13/19 refused quotes in diagnose_v1) and quotes paraphrase, intent or invented code instead of observed text. Requiring that a `diagnose` may reference only a file already read in full this run, unchanged since, will raise the rate of grounded, localized evidence actions and drive pre-read and invented quotes toward zero. Fix quality is not the question here.

## Arms (qwen2.5-coder:1.5b, dev split, 20 tasks = 16 solvable + 4 insufficient-evidence, temperature 0)
- **Control:** `qwen_diagnose` rerun on the current harness (L1 grounding, full read views, diagnose-before-mutation; no read prerequisite). The diagnose_v1 rows are on an earlier harness and are not used for the causal comparison.
- **Treatment:** `qwen_evidence` = control overrides + `read_before_evidence: True`.
- Everything else frozen: corpus, prompts, model digest, temperature, guards, retry policy, lane, oracle, scoring, this gate.

## Mechanism (`read_before_evidence`)
- A `diagnose` call whose `path` was not successfully read in full during this run, or whose file changed since the model last saw it whole (a read, or the agent's own complete write, per the existing read-before-write fingerprint), is refused before execution (`PolicyRejection`, reason `evidence_requires_read`):
  > "Not recorded: <path> has not been read in this task (or changed since it was read). Read <path> first, then quote the exact lines from it."
- The existing verbatim evidence check is unchanged (whitespace-collapsed match, ≥ 5 non-space chars). No normalization is loosened.
- No correct path, candidate path, or edit suggestion is ever injected.

## Localization cap (evaluator; frozen)
A diagnosis is **localized** if its matched seed span is ≤ max(3, file_lines // 4) lines. A defect hit counts only if localized (`hits_defect_localized`). The diagnose_v1 whole-file quotes would score 0 under this rule.

## Definitions (per diagnose call, from recorded rows)
- `pre_read`: no successful `read_file` of that path earlier in the run.
- `valid`: accepted by the tool (verbatim evidence).
- `localized_hit`: valid, localized, and intersecting the reference-patch defect region (±1 line).

## Gate
- **Primary:** solvable tasks with ≥ 1 `localized_hit` rise by ≥ 3 vs control (control expected ≈ 0/16 under the cap).
- **Discipline (must hold in treatment):** pre-read diagnose attempts that are *executed* = 0 by construction; report the count of refused pre-read attempts; the fraction of executed diagnose calls that are valid must be ≥ 0.5 (control: 2/21 ≈ 0.10).
- **Safety:** `lane_false_verified` = 0; false completion on insufficient-evidence tasks 0/4; `damaged_file_tasks` ≤ control.
- **Validity:** 0 invalid rows (truncated reads).
- PASS only if primary, discipline, safety and validity all hold. Hidden-test success is reported, not required.

## Reported, not decisive
Diagnose attempts total / refused pre-read / executed / valid / localized / localized hits; refusal reasons of invalid quotes (hallucinated, prose, wrong file, restated JSON, post-change state); hidden-test passes; edit opportunities; rounds and prompt tokens; escalations; stray files; outcomes on the 4 insufficient-evidence tasks.

## Out of scope
No edit-quality mechanism. Gemma is not run under this gate.
