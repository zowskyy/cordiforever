# DECISIONS — Cordi v2

One row per mechanism. State = what is true in code now. Evidence refers to sections of EXPERIMENT_LOG.md; Knowledge refers to records in RESEARCH_YIELD.md (an ID marked "(refuted)" is cited as rationale against, not as support). A decision changes only with a new pre-registered measurement; supersede by editing the row and appending to the history below.

## Current state

| Mechanism | Calibration key | State | Kind | Rationale | Evidence | Knowledge |
|---|---|---|---|---|---|---|
| Constrained text action protocol (anyOf schema) | `constrained_actions` | **on** in `"1b"` | protocol | executable actions 50/50 probes, 18/18 multi-step, 120/120 dev samples | Reliable tool-call emission; Gate status | CAP-001 |
| Output cap + truncation fail-closed | `sampling.num_predict` 2048 | **on** | safety | runaway generation reproduced and bounded | Reliable tool-call emission | CAP-001 |
| Read-before-overwrite (fingerprints) | `require_read_before_write` | **on** | safety | blocks blind overwrites incl. retry path | Phase 2 step 1 | CAP-008 |
| Structural repeat detection → 0.4 resample → typed escalation | `repeat_retry_temperature` | **on** | safety | ends loops with `EscalationOutcome` instead of max rounds | Phase 2 step 2 | CAP-008 |
| Known-path guard | `require_known_paths` | **on** | safety (not capability) | stray files 4→0, success unchanged 3/10 | Wrong-path guard experiment | CON-008 |
| Named-file read invariant (done gate + exact-path read before mutation) | `require_read_named_files` | **on** | safety | outcomes unchanged; exact-path version blocks the traced config wipe | B; Slice 1 | CON-011 |
| Array hint | `array_guidance` | **off** in `"1b"` | removed noise | misfired and was echoed as final answer | Slice 1 probe; Slice 2 | CON-014 |
| Request path grounding (Option A) | `ground_request_paths` | **off** (superseded) | capability candidate | first path 4/9→8/9 but false done 1→4, one destructive overwrite; superseded by L1 | Option A; Structured editing | CON-010 |
| Structured editing (`replace`, `patch_json`) | `structured_edits` | **off** | safety candidate | cut grounded damage 4→1, no success gain; +54% tokens in lane; Gemma never chose `patch_json` | Structured editing; C | CON-012, METH-008 |
| Bounded task lane | n/a (`run_bounded_task`) | **available**, not used by free-text CLI | verification | 0 false verified / 0 missed success on frozen corpus; corpus self-validation 32/32 | C; Slice 1 | CAP-002 |
| Repository index as optional tools | `repo_tools` | **off** | capability candidate | no localization benefit: models do not choose to use the tools | Localization-only results | CON-001, H-001(refuted) |
| L1 targeted grounding | `targeted_grounding` | **off, not promoted** | capability (localization only) | localization benefit held end-to-end (read recall, gold first touch up, stray files down), but the gate failed: oracle 0→0 for both models and damaged-file tasks rose (0→2, 4→6) | L0/L1/L2; End-to-end L1 | CAP-003, CON-002, H-003(refuted) |
| Full read views | `full_read_views` | **off** (experimental control in `diagnose_v1`, `gemma_progress_v1`, `qwen_evidence_v1`) | control | removes the 200-char preview confound; not a production read strategy | diagnose_v1 | METH-001 |
| Diagnose before mutation | `diagnose_before_mutation` | **off, not promoted** | capability candidate (constrains transformation) | gate diagnose_v1 FAILED: oracle 0→0 Gemma, 0→1 Qwen. Gemma never called diagnose; Qwen's quotes failed verification 19/21. Damage fell to 0 by suppressing edits; tokens +97% (Qwen) | diagnose_v1 | CON-003, H-005(refuted), METH-005 |
| Progress recovery messages (Gemma) | `progress_recovery` | **off, not promoted** | capability candidate | gate gemma_progress_v1 FAILED: edit opportunity 2/16 → 2/16; all 26 recoveries followed by the identical read | gemma_progress_v1 | CON-004, H-007(refuted), Q-004 |
| Read before evidence (Qwen) | `read_before_evidence` | **off, not promoted** | evidence discipline candidate | gate qwen_evidence_v1 FAILED (valid run, frozen scorer b309…): localized hits 0→0; executed pre-read 14→0 but valid 2/13; damaged 0→1. After refusal + full read, 7/7 re-diagnoses still invalid | qwen_evidence_v1 | CAP-007, CON-005, H-008(refuted) |
| Deterministic evidence extraction (Qwen) | `evidence_extraction` | **off, not promoted** | evidence mechanism candidate | gate qwen_extract_v1 FAILED on the damaged-file guardrail (5 > control 1) while the primary PASSED: localized-hit tasks 0 → 8, precision 0.82, spans ≤ 2 lines; hidden-test passes 1 → 3. Remaining localized-hit failures are mostly mechanical edits damaging the correctly located file | qwen_extract_v1 | CAP-004, CON-006, H-009 |
| Bounded localized editing (Qwen) | `localized_edits` | **off, not promoted** | edit mechanism candidate | gate qwen_localedit_v1 FAILED on P2 (hidden-test passes 3 → 1) while P1 PASSED (damaged 5 → 0). Edit executed 9 → 2: 10/14 edits used a leading-slash pointer form on Python symbols (`/divide`); damage fell because destructive writes were refused and edits failed validation, not because edits succeeded | qwen_localedit_v1 | CAP-005, CON-007, H-010 |
| Explicit selector kind for bounded edits (Qwen) | `explicit_selector_kind` (+ `localized_edits`, `evidence_extraction`, …) | **dev gate PASSED; heldout PARTIAL (b); not in any preset** | edit interface | dev qwen_selectorkind_v1 PASS (syntax 4/14 → 13/13, executed 2 → 6, passes 1 → 3). Heldout qwen_selectorkind_heldout_v1 PARTIAL (b): safety and damage replicated (T 0 vs reference 4), syntax 15/15 vs control 5/10, but edit-executed gain +2 < 3 and completion 1/16 = reference. Kept as the Qwen experimental base; no preset promotion | qwen_selectorkind_v1; qwen_selectorkind_heldout_v1 | CAP-005, CAP-006, H-011, Q-002 |
| L2 evidence-gated completion | `evidence_gated_completion` | **off, held** | safety candidate | no gain over L1 on this corpus (L1 already made unsupported declarations 0) | L0/L1/L2 | CON-009 |
| Qwen reasoning roles (architect/integrator/cartographer) | n/a | **not assigned** | architecture | not materially better than Gemma at the floor; localization not higher | Slice 1 decision table | CON-013 |
| Mastermind / multi-branch architecture (incl. 3+3 teams) | n/a | **frozen** | architecture | no multi-agent configuration exists or has been run; every experiment so far is one model + deterministic verifier. Coordination is to be tested only as a ladder: best single agent → + deterministic verifier (current) → 2 agents with one structured handoff (diagnosis + evidence + target + confidence; accept/reject/revise) → bounded revision → 3 specialized → larger teams. The next rung is registered only after the single-agent Qwen path is closed, and each rung must beat the rung below on the same tasks without more damage, false verification or instability | Slice 1 plan; user direction 2026-09-14 | CON-013 |

## Pending decision
- **Ruff / mypy:** deferred. Introduce later as a separate engineering change: establish a baseline, then ratchet; never as a sudden CI gate during capability research (MNT-05 reports them as unconfigured).
- **Private final oracle:** future final heldout evaluation uses a private oracle outside public git history; the committed oracle is treated as published (METH-009). Not scheduled.
- **After qwen_selectorkind_heldout_v1 (PARTIAL b):** no preset change; no next gate registered yet. The next dev experiment isolates replacement-content quality (Q-002): one factor, the contract or mechanism governing replacement content, with selector resolution, extraction, abstention, localization and bounded-edit validation unchanged, pre-registered before implementation. Abstention (Q-003) stays separate. Milestone (3) not reached; coordination frozen.
- [Superseded] **After qwen_selectorkind_v1 (PASS):** decided: (a) heldout replication registered as qwen_selectorkind_heldout_v1 before any preset change (Q-001); (b) the next dev factor after heldout closure is replacement quality (Q-002); abstention (Q-003) stays a separate later safety hypothesis. No preset change until the heldout classification. The recorded break point is now replacement quality (wrong_edit_choice 3, whole-file symbol replacement 1, JSON value syntax 1), with category-3 edits on unsolvable tasks still present (1, no damage).
- [Superseded] **After qwen_localedit_v1 (FAILED on P2):** no next gate registered. Recorded break point: edit execution, specifically the `edit` target interface (Python symbols given in JSON-pointer form). Selector/interface changes need their own pre-registration.
- [Superseded] **After qwen_extract_v1 (FAILED, primary passed):** no next gate registered. With extraction deterministic, Qwen localizes (8/16); the recorded downstream bottleneck is edit execution (mechanical_failure 4 of 5 remaining hit tasks, 3 with damage) plus edits on insufficient-evidence tasks (2).
- [Superseded] After qwen_evidence_v1 (FAILED): the recorded bottleneck for Qwen was quote fidelity after a complete read (not read ordering). qwen_extract_v1 confirmed and removed it.
- **EXP-19 closure must keep three milestones separate** (a heldout PASS can support the first two without implying the third):
  - (1) selector mechanism generalized (CAP-006 / H-011 on heldout)
  - (2) single-agent capability generalized (heldout outcome clauses)
  - (3) single-agent capability strong enough to justify coordination research. Not claimable from EXP-19; it requires the single-agent path to close, including replacement quality (Q-002).
- **Coordination prerequisite:** the two-agent handoff becomes active only after milestone (3). A second model's role must be evidence-derived: first benchmark isolated candidate functions (diagnosis critique, evidence checking, alternative hypotheses, proposed-edit review) against Qwen and against deterministic logic. A role is a candidate only if the model beats both on that narrow function. No role is assigned by name ("reviewer", "critic", "researcher").- **Gemma action-masking (coordinator-control experiment):** deferred, not scheduled; only after Qwen is diagnosed (Q-004, H-013).
- [Superseded, kept for the record] ~~Next intervention target: semantic interpretation/edit quality; no mechanism chosen yet~~. `diagnose_v1` was chosen and failed. Its two constraints were applied: it constrained the transformation step, and the 200-char preview was controlled via `full_read_views`.
- **Compact read preview (200 chars):** unchanged in production. Treat it as a measured confound; any production change is a pre-registered factor (METH-001).
- **L1 re-evaluation:** only as part of a combination whose own gate is met. L1 is not credited for success alone (CAP-003, CON-002).
- **Re-test L2** once localization recall is high enough that completion errors, not discovery errors, dominate. Not yet the case (CON-009).

## History
- 2026-09-14 Published to public GitHub zowskyy/cordiforever; byte-exact storage enforced; deterministic verification offloaded to GitHub Actions (5 staged jobs, all passing, 0 scorers executed). Model inference and experiment execution stay local.
- 2026-09-14 qwen_selectorkind_heldout_v1 closed PARTIAL (b) on heldout (frozen scorer f70b7718…, run once). Safety and damage prevention replicated; selector execution gain not confirmed; completion near floor. No preset change; Q-001 closed; next dev factor Q-002.
- 2026-09-14 Multi-agent teams frozen (no 3+3). Coordination research limited to the ladder in the Mastermind row, with a two-agent structured handoff as the only coordination branch after the single-agent path; no coordination experiment is registered while EXP-19 is open.
- 2026-09-13 `require_known_paths` enabled (safety, not capability).
- 2026-09-13 Option A grounding held; stricter gate defined.
- 2026-09-13 Build B + C, not A (model-declared checks are circular trust); structured editing off by default.
- 2026-09-13 Slice 1: no Qwen reasoning roles; build deterministic localization next.
- 2026-09-14 `array_guidance` off in `"1b"`.
- 2026-09-14 Optional repo tools: not promoted.
- 2026-09-14 L1 advances to end-to-end evaluation; L2 held.
- 2026-09-14 qwen_selectorkind_v1 gate PASSED (P1 damaged 0; P2 hidden-test passes 3, at the bound; all guardrails; valid). Scored once with frozen scorer 135a71f9…. First gate PASS in the program; no preset change made.
- 2026-09-14 qwen_localedit_v1 gate FAILED on P2 (hidden-test passes 1 < 3); P1 PASSED (damaged 0); all guardrails held. Scored once with frozen scorer 723fcc8d…. Not promoted.
- 2026-09-14 qwen_extract_v1 gate FAILED on damaged-file guardrail (5 > 1); primary PASSED (localized hits 0 → 8). Scored once with frozen scorer 9def0b99…. Not promoted.
- 2026-09-14 qwen_evidence_v1 gate FAILED (primary 0 gain; valid fraction 0.15; damaged 0→1). Scored once with frozen scorer b309…; classifier validation 15/19.
- 2026-09-14 qwen_evidence_v1 registered and built (harness 0d5b65e2ee00); scorer frozen before inspection; runs in progress.
- 2026-09-14 Gemma progression conclusion frozen (textual recovery ineffective); action-masking deferred.
- 2026-09-14 Harness maintenance: duplicate-read notice repaired (not an experiment); repaired Gemma baseline recorded.
- 2026-09-14 gemma_progress_v1 gate FAILED (valid; drift check 0). Text-level recovery guidance does not change Gemma's next action.
- 2026-09-14 diagnose_v1 gate FAILED for both models (valid run, 0 invalid rows). No 2×2 follow-up. First natural lane verified_done agreed with the oracle (n=1).
- 2026-09-14 End-to-end L1 gate FAILED (oracle 0/16 → 0/16 both models; damaged-file tasks rose). L1 not promoted. Localization ruled out as the end-to-end bottleneck on this corpus.
