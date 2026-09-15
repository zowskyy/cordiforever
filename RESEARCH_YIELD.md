# RESEARCH_YIELD — Cordi v2

What the project currently knows because of completed research, and how that constrains future research.
- `EXPERIMENT_LOG.md` = what happened (measurements, provenance, verdicts).
- `DECISIONS.md` = what is enabled, disabled, held or deferred.
- This file = accumulated knowledge.

Validated by `scripts/validate_research_state.py` (run it after every edit to any of the three files).

Rules:
- Every record cites registry IDs below. Every registry row names an exact `EXPERIMENT_LOG.md` heading.
- A gate FAIL does not erase sub-findings, but a record built on a failed gate states what that failure prevents us from claiming (`not_established`).
- Evidence carrying a confound needs a `qualification` naming the confound ID.
- Statuses:
  - CAP / CON / METH: SUPPORTED, PARTIALLY_SUPPORTED, SUPERSEDED
  - H: OPEN, SUPPORTED, PARTIALLY_SUPPORTED, FALSIFIED, SUPERSEDED
  - Q: OPEN, DEFERRED, CLOSED
- `closed_by` marks the experiment that settled an H. Retesting a closed H needs a registry `changed_condition`.
- Confidence (required on CAP, CON and settled H records):
  - `mechanism-valid` = the mechanism behaves as specified (tests or mechanism metrics); no outcome benefit shown
  - `dev-supported` = the outcome claim is supported on the dev split only
  - `heldout-supported` = replicated on the untouched heldout split (requires heldout registry evidence)
  - A dev-supported record is never described as generally established.
- From EXP-19 onward every closure also needs a Semantic Audit of each new or modified record: DIRECTION, POPULATION, COMPARISONS, DESCRIPTIVE VS GATE, CONFOUNDS, CAUSAL LANGUAGE, NARROW FINDINGS, NARROW PASS.
- The heldout split is replication-only: never used to design, tune or select a mechanism.
- From EXP-18 onward every completed experiment needs a Research Delta before the next is registered (unless `parallel` = yes).

## Experiment registry

`basis`:
- `frozen_gate` = gate file + frozen verdict section
- `stated_criterion` = a decision rule recorded before or with the run, without a frozen gate file
- `no_gate` = measurement without a pass/fail rule (classified INCONCLUSIVE)

| ID | log_section | gate | split | verdict | basis | confounds | tests | changed_condition | parallel | closure | updates | decision | delta | audit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EXP-01 | Reliable tool-call emission | none | other | PASS | stated_criterion | none | - | - | no | closed | CAP-001 | constrained actions on in "1b" | no | no |
| EXP-02 | Wrong-path guard experiment | none | other | INCONCLUSIVE | no_gate | FND-01 | - | - | no | closed | CON-008 | known-path guard on (safety, not capability) | no | no |
| EXP-03 | Option A — request path grounding | none | other | FAIL | stated_criterion | FND-01 | - | - | no | closed | CON-010 | request path grounding held | no | no |
| EXP-04 | Structured editing (2026-09-13) | none | other | FAIL | stated_criterion | none | - | - | no | closed | CON-010, CON-012, METH-008 | grounding held; structured editing off | no | no |
| EXP-05 | B — completion invariant: named existing files must be read | none | other | INCONCLUSIVE | no_gate | none | - | - | no | closed | CON-011 | named-file invariant on; exact-path variant built | no | no |
| EXP-06 | C — bounded task lane | none | other | INCONCLUSIVE | no_gate | none | - | - | no | closed | CAP-002, CON-012 | bounded lane available | no | no |
| EXP-07 | Slice 1 — realistic repo corpus, exact-path B, controlled Gemma/Qwen baselines | none | dev | INCONCLUSIVE | stated_criterion | FND-02, FND-03 | - | - | no | closed | CON-013 | no Qwen reasoning roles; build localization next | no | no |
| EXP-08 | Localization-only results | none | dev | FAIL | stated_criterion | FND-02, FND-03 | H-001 | - | no | closed | CON-001, H-001 | optional repo tools not promoted | no | no |
| EXP-09 | L0 / L1 / L2 localization experiment | none | dev | PASS | stated_criterion | FND-02, FND-03 | H-002 | - | no | closed | CAP-003, H-002 | L1 advances to end-to-end | no | no |
| EXP-10 | L0 / L1 / L2 localization experiment | none | dev | FAIL | stated_criterion | FND-02, FND-03 | - | - | no | closed | CON-009 | L2 held | no | no |
| EXP-11 | End-to-end L1 — gate verdict | e2e_l1_v1.md | dev | FAIL | frozen_gate | FND-02, FND-03 | H-003 | - | no | closed | CON-002, H-003, H-004 | L1 not promoted | no | no |
| EXP-12 | diagnose_v1 — gate verdict | diagnose_v1.md | dev | FAIL | frozen_gate | FND-03 | H-005 | - | no | closed | CON-003, H-005, H-004, METH-005, FND-05 | diagnose-before-mutation not promoted | no | no |
| EXP-13 | Repaired Gemma baseline: gemma_fullread on harness af9f8800f3b7 | none | dev | INCONCLUSIVE | no_gate | none | H-006 | - | no | closed | H-006, METH-001, METH-002 | premature-done guard dropped; new Gemma baseline | no | no |
| EXP-14 | gemma_progress_v1 — gate verdict | gemma_progress_v1.md | dev | FAIL | frozen_gate | none | H-007 | - | no | closed | CON-004, H-007, H-013, METH-004 | progress recovery not promoted; Gemma conclusion frozen | no | no |
| EXP-15 | qwen_evidence_v1 — gate verdict | qwen_evidence_v1.md | dev | FAIL | frozen_gate | none | H-008 | - | no | closed | CAP-007, CON-005, H-008, METH-003 | read-before-evidence not promoted | no | no |
| EXP-16 | qwen_extract_v1 — gate verdict | qwen_extract_v1.md | dev | FAIL | frozen_gate | none | H-009 | - | no | closed | CAP-004, CON-006, H-009, H-010, H-014, FND-04 | evidence extraction not promoted | no | no |
| EXP-17 | qwen_localedit_v1 — gate verdict | qwen_localedit_v1.md | dev | FAIL | frozen_gate | none | H-010 | - | no | closed | CAP-005, CON-007, H-010, H-011, METH-006 | localized edits not promoted | no | no |
| EXP-18 | qwen_selectorkind_v1 — gate verdict | qwen_selectorkind_v1.md | dev | PASS | frozen_gate | none | H-011 | - | no | closed | CAP-006, H-011, H-012, H-014, Q-001, Q-002, Q-003 | gate passed (dev); no preset change; decisions pending | yes | no |
| EXP-19 | qwen_selectorkind_heldout_v1 — gate verdict | qwen_selectorkind_heldout_v1.md | heldout | PARTIAL | frozen_gate | none | H-011 | replication on the untouched heldout split (no mechanism change) | no | closed | CAP-002, CAP-005, CAP-006, CON-007, H-011, H-012, H-014, Q-001 | no preset change; replacement quality (Q-002) next on dev | yes | yes |
| EXP-20 | qwen_astnoop_v1 — gate verdict | qwen_astnoop_v1.md | dev | PARTIAL | frozen_gate | none | H-012 | new factor: structural no-op refusal for python_symbol replacements | no | closed | CAP-009, CON-015, H-012, Q-002 | no preset change; mechanism kept available (flag off by default); next Q-002 factor decided by user | yes | yes |
| EXP-21 | qwen_donelatch_v1 — gate verdict | qwen_donelatch_v1.md | dev | PARTIAL | frozen_gate | none | H-012 | new factor: completion contingent on mutation result (latch after failed mutation) | no | closed | CON-015, CON-016, H-012, Q-002 | no preset change; latch kept available (flag off by default); next Q-002 factor decided by user | yes | yes |
| EXP-22 | qwen_formatcontract_v1 — gate verdict | qwen_formatcontract_v1.md | dev | PARTIAL | frozen_gate | none | H-012 | new factor: type-specific replacement-format contract shown before edit execution | no | closed | CON-017, H-012, Q-002, METH-007, MNT-06 | no preset change; contract kept available (flag off by default); next stage offline failure taxonomy (diagnosis, not an experiment) | yes | yes |

EXP-09 and EXP-10 share one log section: EXP-09 is the L1 arm (criterion met), EXP-10 the L2 arm (criterion not met). EXP-11's gate file was written after evaluation, from the pre-registered text (noted in the file).

## Findings and maintenance (not experiments)

| ID | log_section | kind | summary |
|---|---|---|---|
| FND-01 | Structured editing (2026-09-13) | confound | compact-mode compression fabricated JSON content before the fix; earlier compact measurements are invalid for quantitative comparison |
| FND-02 | Finding: compact reads show at most 200 characters | confound | compact reads truncated to 200 chars; "read the gold file" did not imply "saw the defect" |
| FND-03 | Finding: the harness tells the model to stop after a repeated read | confound | a false "task completed… Finish now" notice after repeated reads induced premature done |
| MNT-01 | Harness maintenance: duplicate-call notice repair | maintenance | the FND-03 notice repaired outside any treatment arm |
| FND-04 | qwen_extract_v1 — damaged-case classification | forensics | 5/5 damaged cases via full-content write_file: 3 localized-then-destructive, 2 unsolvable-then-edited |
| FND-05 | diagnose_v1 — forensic classification | forensics | Gemma 0/10 diagnose attempts; Qwen 2/21 valid quotes, both whole-file |
| MNT-02 | Proficiency phase 2 — step 1: read-before-overwrite invariant | maintenance | per-file fingerprint read-before-overwrite guard; blind overwrite refused with contents; 4 tests fail when disabled; agent_task_eval unchanged 3/5 |
| MNT-03 | Proficiency phase 2 — step 2: structural repeat detection + typed escalation | maintenance | repeat keys with mutation version; one resample at 0.4 then typed escalation; delete_logs ended in round 2 (5.2 s) instead of 12 rounds (17 s) |
| MNT-04 | Slice 2 — deterministic repository intelligence + tool adoption | maintenance | keyword-triggered array hint removed from the measured harness after misfiring and being echoed as an answer (Slice 1 probe) |
| MNT-05 | Repository publication and CI offload | maintenance | public GitHub publication (oracle and results included), byte-exact storage via .gitattributes, staged deterministic CI with read-only evidence verification (0 scorers executed) |
| MNT-07 | Furthest-reached bottleneck taxonomy — methodology freeze | methodology | diagnostic-analysis methodology frozen (not an experiment, no capability claim, no Q-002 conclusion): specification cf5b8764…, classifier 6817e1a7…, mutation runner 8352890c…, tests 055873e8… and 658e4aa9…; 100/100 synthetic checks, 30/30 mutation expectations (29 caught, 1 proven equivalent); developed without real trajectories; real classification not yet performed |
| MNT-06 | Execution-efficiency audit | maintenance | cold one-task-per-call ~52 s/task vs warm resident model ~31 s/task (dominant cost: model prompt evaluation and generation); cold/warm byte-identical on 2/2 control tasks; experiment-execution v2; in EXP-22 a 5-task invocation ended at 99.5 MB available RAM and batch 2 kept 243–648 MB; warm-batched drift reproduced the frozen control 20/20 (infrastructure evidence, not EXP-22 scientific evidence) |

## Causal trajectory (reconstructed)

1. Optional repository tools did not improve localization; models did not adopt them. (H-001 FALSIFIED, CON-001)
2. Deterministic targeted grounding improved localization for both models. (H-002 SUPPORTED, CAP-003)
3. Better localization did not raise end-to-end success; the edit stage was suspected. (H-003 FALSIFIED, CON-002, H-004)
4. Diagnose-before-mutation with model-authored quotes failed. Gemma never adopted it; Qwen's quotes were ungrounded or whole-file. H-004 was superseded: failures sat before the edit. (H-005 FALSIFIED, CON-003, METH-005)
5. Gemma: the apparent premature completion was harness-induced (H-006 FALSIFIED, METH-001/002). Fact-only recovery text did not change repetition (H-007 FALSIFIED, CON-004). Masking deferred (H-013 OPEN).
6. Qwen: forcing read-before-evidence fixed ordering but not quote fidelity. (H-008 FALSIFIED, CAP-007, CON-005)
7. Deterministic extraction from the read snapshot made Qwen localize defect elements; full-file rewrites then damaged correct targets. (H-009 SUPPORTED, CAP-004, H-010, CON-006)
8. Bounded localized edits removed damage but a mixed selector field broke execution. (CAP-005, CON-007, H-010 SUPPORTED, H-011)
9. An explicit selector kind restored execution and passed the gate at the completion bound. The next bottleneck is replacement quality. (CAP-006, H-011 PARTIALLY_SUPPORTED, H-012 OPEN)
10. Heldout replication was PARTIAL (b): safety and damage prevention replicated (CAP-002, CAP-005 heldout-supported), and the selector syntax error and its fix reappeared. But valid selectors mostly failed on replacement content, so the execution gain fell below threshold and completion stayed near floor. Replacement quality stays the next dev target. (CAP-006 dev-supported, H-011 contradicted in part, H-012 OPEN)

## Capabilities

### CAP-001 — Constrained anyOf decoding makes Gemma emit executable single actions
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-01
- contradicted_by: none
- scope: gemma3:1b, Ollama format schema, temperature 0 and 0.4, num_predict 2048
- establishes: executable actions 50/50 single-turn probes, 18/18 multi-step replies, 120/120 dev samples; truncation fail-closed
- not_established: semantic correctness of actions (82–87% on the semantic baseline); zero-failure rate (n=150 lower bound ~97.6%)
- consequence: action syntax is not a research target; failures are semantic or control failures
- redundant: further protocol-emission reliability runs under the same schema and model
- supersedes: none
- next: none

### CAP-002 — The bounded lane plus independent hidden oracle keeps false verification at zero
- status: SUPPORTED
- confidence: heldout-supported
- evidence: EXP-06, EXP-11, EXP-12, EXP-14, EXP-15, EXP-16, EXP-17, EXP-18, EXP-19
- contradicted_by: none
- scope: this corpus and oracle; lane checks as specified per task
- qualification: EXP-11 (FND-02, FND-03) and EXP-12 (FND-03) ran under read-truncation and false-completion confounds; those affect what the model did, not whether the lane's verdict agreed with the independent oracle
- establishes: lane_false_verified = 0 in every scored run; oracle catches a forced always-pass verifier; hidden-test passes co-occurred with zero false verification (EXP-12 Qwen 1, EXP-15 1, EXP-16 3, EXP-18 3); first natural verified_done agreed with the oracle (EXP-12); heldout gated safety clause S held for the qwen_selectorkind stack (false verified 0; its single heldout pass was lane verified_done and oracle pass, EXP-19)
- not_established: lane precision at scale; behavior on tasks whose checks are weaker than the hidden tests
- consequence: model completion claims stay non-authoritative; gates score hidden-test success, not model claims
- redundant: re-testing oracle independence without a change to lane or oracle code
- supersedes: none
- next: none

### CAP-003 — Deterministic targeted grounding (L1) improves localization for both models
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-09, EXP-11
- contradicted_by: none
- scope: dev split, 16 localization tasks, compact reads
- qualification: FND-02 and FND-03 affected both arms equally; declared-file recall and precision are comparative, not absolute
- establishes: file recall Gemma 0.083→0.583, Qwen 0.312→0.688; precision up; invented paths down; read recall also up end-to-end
- not_established: any end-to-end success gain (EXP-11 FAIL)
- consequence: grounding is a localization component, not a promotable capability on its own
- redundant: L1-only localization reruns under equivalent harness
- supersedes: none
- next: none

### CAP-004 — Deterministic evidence extraction lets Qwen identify defective program elements
- status: PARTIALLY_SUPPORTED
- confidence: dev-supported
- evidence: EXP-16
- contradicted_by: none
- scope: qwen2.5-coder:1.5b, dev split, exact Python-symbol and JSON-pointer selectors, read snapshot only
- establishes: localized-hit tasks 0→8 (primary PASSED), precision 0.82, spans ≤ 2 lines; 0 extraction without a full read
- not_established: a promotable mechanism: the gate FAILED on damage (5 > 1), so extraction cannot be claimed safe or end-to-end beneficial alone; no heldout replication
- consequence: keep extraction as the base for edit experiments; do not return to model-authored quotes
- redundant: quote-fidelity or read-order interventions for Qwen under equivalent conditions
- supersedes: none
- next: Q-005

### CAP-005 — The bounded localized-edit primitive prevents destructive writes
- status: SUPPORTED
- confidence: heldout-supported
- evidence: EXP-17, EXP-18, EXP-19
- contradicted_by: none
- scope: Qwen, edit_symbol replacing one Python definition or one JSON pointer value; write_file refused on existing files
- establishes: damaged-file tasks 5→0 and 0 in EXP-18 (dev); no successful edit damaged a file; unsolvable tasks produced no damage; on heldout the gated P1h clause held for the qwen_selectorkind stack (0 damaged vs 4 for the full-write reference, EXP-19), and the bounded-edit control also had 0 (descriptive)
- not_established: that it preserves completion by itself (EXP-17 FAILED P2, 3→1); that EXP-17's damage reduction reflects correct edits (partly refusals and failed validation)
- consequence: keep bounded edits as the edit channel in further Qwen experiments
- redundant: re-testing full-file write_file on existing files under equivalent conditions
- supersedes: none
- next: none

### CAP-006 — An explicit selector kind restores bounded-edit execution
- status: PARTIALLY_SUPPORTED
- confidence: dev-supported
- evidence: EXP-18, EXP-19
- contradicted_by: EXP-19 (heldout: cumulative edit-executed gain over control +2, below the pre-registered +3)
- scope: Qwen, dev split, single temperature-0 run, n=16
- establishes: dev: selector syntax valid 4/14→13/13; python_symbol edits successful 1/12→8/11; edit executed (cumulative) 2→6; hidden-test passes 1→3; damage 0; gate PASS. Heldout (EXP-19, PARTIAL b): syntax valid 15/15 vs control 5/10 (descriptive), but the execution gain did not reach the threshold
- not_established: that the execution gain generalizes (heldout M failed); a stable or large effect (dev P2 met at its bound); replacement correctness; any completion gain on heldout (T 1/16 = reference 1/16)
- consequence: selector representation is no longer the first bottleneck; do not change resolvers or add normalization
- redundant: selector-form experiments with a single mixed target field
- supersedes: none
- next: Q-001

### CAP-007 — A read-before-evidence guard eliminates diagnoses of unread files
- status: SUPPORTED
- confidence: mechanism-valid
- evidence: EXP-15
- contradicted_by: none
- scope: Qwen, diagnose tool, full read views
- establishes: executed pre-read diagnoses 14→0; nonexistent-file quotes 4→0
- not_established: quote validity (2/13) or localized hits (0); the gate FAILED
- consequence: the prerequisite is cheap and correct, but not a localization mechanism
- redundant: none
- supersedes: none
- next: none

### CAP-008 — Deterministic read-before-overwrite and structural repeat detection bound blind overwrites and loops
- status: SUPPORTED
- confidence: mechanism-valid
- evidence: MNT-02, MNT-03
- contradicted_by: none
- scope: gemma3:1b "1b" preset; unit tests plus agent_task_eval
- establishes: blind overwrites are refused with the file contents shown (mutation check: 4 tests fail when disabled); repeated failed calls end in a typed escalation instead of max rounds (delete_logs: round 2 instead of 12)
- not_established: any task-success gain (agent_task_eval 3/5 unchanged)
- consequence: kept on as safety invariants; not credited as capability
- redundant: none
- supersedes: none
- next: none

### CAP-009 — Structural no-op refusal prevents accepted AST-identical Python replacements
- status: SUPPORTED
- confidence: mechanism-valid
- evidence: EXP-20
- contradicted_by: none
- scope: Qwen, dev split, python_symbol bounded edits, single temperature-0 run, n=16 solvable
- establishes: accepted structural no-op edits 2 (control, drift) → 0 (treatment); both refusals on the two pre-identified restatement tasks; damage 0, false verified 0 and all other safety clauses held; no other trajectory changed (18/20 tasks identical to control, the other 2 differ only in the refused call)
- not_established: any completion gain (passes 3 → 3, gate C NO_IMPROVEMENT); that refusal leads to a substantive edit; behavioral equivalence (the detector is structural only)
- consequence: executed-edit counts no longer include cosmetic restatements when the flag is on; the flag is kept available, off by default
- redundant: none
- supersedes: none
- next: Q-002
## Constraints

### CON-001 — Offering repository tools as optional actions does not improve localization
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-08
- contradicted_by: none
- scope: gemma3:1b and qwen2.5-coder:1.5b, constrained actions, localization-only corpus
- qualification: FND-02 and FND-03 were present in both arms; the non-adoption counts are behavioral, not affected by read truncation
- establishes: models did not adopt the tools (Qwen made no tool call on 11/16 and 9/16 tasks; Gemma read invented paths on 14–16 of 18–21 path calls); pre-registered improvement rules not met
- not_established: that the repository index itself is useless (used deterministically it later helped: CAP-003)
- consequence: deliver repository facts deterministically; do not rely on model tool choice
- redundant: re-offering optional repository tools without changing adoption conditions
- supersedes: none
- next: none

### CON-002 — Localization improvement alone did not raise end-to-end success
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-11
- contradicted_by: none
- scope: dev corpus, pre-extraction harness, compact reads
- qualification: FND-02 truncated reads and FND-03 induced premature done in both arms; the null comparison holds, absolute Gemma behavior claims do not
- establishes: hidden-test passes 0→0 for both models with L1; damaged-file tasks rose (0→2, 4→6)
- not_established: that localization never matters (it did in combination: EXP-16, EXP-18)
- consequence: L1 is credited only inside combinations with their own passing gate
- redundant: re-running L1-only end-to-end under equivalent harness
- supersedes: none
- next: none

### CON-003 — Diagnose-before-mutation with model-authored quotes did not improve repair
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-12
- contradicted_by: none
- scope: both models, full read views, model-written evidence quotes
- qualification: FND-03 was present; Gemma's diagnose non-adoption is unaffected, and Qwen's quote refusals were classified individually (FND-05)
- establishes: hidden-test passes 0→0 Gemma, 0→1 Qwen; Gemma 0 diagnose calls; Qwen 2/21 valid quotes, both whole-file
- not_established: that diagnosis as a concept is useless (with deterministic extraction it localized: CAP-004)
- consequence: evidence must not depend on model verbatim copying
- redundant: diagnose-before-mutation with model-authored quotes under equivalent conditions
- supersedes: none
- next: none

### CON-004 — Fact-only recovery text does not change Gemma's repeated-read trajectory
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-14
- contradicted_by: none
- scope: gemma3:1b, repaired harness, recovery delivered as the tool result of the repeated call
- establishes: edit opportunity 2/16→2/16; 26/26 recoveries followed by the identical read; drift check 0
- not_established: that control mechanisms (action masking) would fail
- consequence: do not add text feedback variants for Gemma progression
- redundant: further wording or placement variants of recovery text for Gemma under equivalent harness
- supersedes: none
- next: Q-004

### CON-005 — Qwen does not produce verbatim localized quotes even after a full read
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-15
- contradicted_by: none
- scope: qwen2.5-coder:1.5b, diagnose evidence argument, whitespace-tolerant verbatim check
- establishes: executed valid 2/13; after refusal plus full read, 7/7 re-diagnoses still invalid (restated JSON 4, invented 3, prose 2); 0 localized
- not_established: inability to identify defects (CAP-004 shows it can name them)
- consequence: move exact copying to deterministic code
- redundant: quote-fidelity prompting; loosening the verbatim check (2/19 at most rescuable, FND-05)
- supersedes: none
- next: none

### CON-006 — Full-content write_file on existing files is the damage channel after localization
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-16
- contradicted_by: none
- scope: Qwen, extraction harness
- establishes: 5/5 damaged tasks came through full-content write_file (FND-04): JSON restatement 2, fragment-as-file 1, unsolvable-task fragment writes 2
- not_established: that bounded edits yield correct fixes
- consequence: existing files change only through bounded edits in Qwen experiments
- redundant: none
- supersedes: none
- next: none

### CON-007 — A single mixed selector field induced JSON-pointer syntax on Python edit targets
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-17, EXP-19
- contradicted_by: none
- scope: Qwen, edit action with one target field for both kinds and a `/key` example
- establishes: dev: 10/14 edits used a leading-slash form (`/divide`); edit executed 7→2 (cumulative); hidden-test passes 3→1. Heldout control (EXP-19, descriptive, not a gate clause): 5/10 edit targets in leading-slash form
- not_established: that Qwen cannot express bounded edits (CAP-006 shows it can with explicit kinds)
- consequence: selector kinds must be explicit in the action schema
- redundant: mixed-field selector interfaces
- supersedes: none
- next: none

### CON-008 — The known-path guard is defensive, not corrective
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-02
- contradicted_by: none
- scope: gemma3:1b, frozen 10-task corpus
- qualification: FND-01 invalidates quantitative comparison; the repeat pattern (0/8 repaired) is behavioral
- establishes: stray files removed, success unchanged 3/10; Gemma repeated the refused path 8/8 despite candidates
- not_established: any capability gain
- consequence: kept on for safety only, not credited as capability
- redundant: path-guard wording variants expecting repair
- supersedes: none
- next: none

### CON-009 — L2 evidence-gated completion added nothing over L1 on this corpus
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-10
- contradicted_by: none
- scope: localization-only corpus
- qualification: FND-02 and FND-03 present in both arms; L1 already reduced unsupported declarations to 0
- establishes: recall and precision not ≥ L1 (criterion failed); the gate fired only on tasks that declared nothing
- not_established: L2's value once completion errors dominate
- consequence: L2 held; re-test only when completion errors dominate
- redundant: L2 re-tests before that condition
- supersedes: none
- next: none

### CON-010 — Request path grounding (Option A) converted escalations into false completions
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-03, EXP-04
- contradicted_by: none
- scope: gemma3:1b, frozen 10-task corpus
- qualification: EXP-03 numbers are under FND-01; EXP-04's four-condition rerun is on the fixed harness and confirms the gate not met
- establishes: first-attempt path 4/9→8/9 but false done 1→4 with one destructive overwrite; the stricter grounding gate was not met (false done 2 vs 1)
- not_established: that targeted grounding fails (CAP-003 is a different mechanism)
- consequence: request path grounding stays off, superseded by targeted grounding
- redundant: Option A reruns
- supersedes: none
- next: none

### CON-011 — A read-before-done gate does not force looking before acting
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-05
- contradicted_by: none
- scope: gemma3:1b, frozen corpus
- establishes: identical outcomes 3/10; traced config wipe happened before the forced read
- not_established: value of exact-path read-before-mutation (built afterward, not separately gated)
- consequence: invariants must act before mutation, not only before completion
- redundant: done-time read gates as a damage control
- supersedes: none
- next: none

### CON-012 — Structured replace/patch editing reduced damage without success gain for Gemma
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-04, EXP-06
- contradicted_by: none
- scope: gemma3:1b, frozen corpus
- establishes: grounded damage 4→1; success not raised; Gemma never chose patch_json; lane token cost +54%
- not_established: behavior of bounded symbol-level edits for Qwen (CAP-005)
- consequence: structured editing stays off for Gemma
- redundant: re-enabling replace/patch_json for Gemma under equivalent conditions
- supersedes: none
- next: none

### CON-013 — At the performance floor, model comparison cannot discriminate
- status: PARTIALLY_SUPPORTED
- confidence: dev-supported
- evidence: EXP-07
- contradicted_by: none
- scope: Slice 1 baselines, both models 0/16
- qualification: FND-02 and FND-03 present in both arms
- establishes: "Qwen not materially better" shown; "not worse" not shown
- not_established: relative model capability
- consequence: no Qwen reasoning roles assigned on that evidence
- redundant: floor-level model comparisons
- supersedes: none
- next: none

### CON-014 — Keyword-triggered array hints misfire on unrelated tasks
- status: SUPPORTED
- confidence: dev-supported
- evidence: MNT-04, EXP-07
- contradicted_by: none
- scope: ArrayHelper keyword relevance in the lite loop
- qualification: EXP-07 ran under FND-02 and FND-03; the observation is the hint text being echoed as a final answer, independent of read truncation or the completion notice
- establishes: the hint was injected on unrelated tasks and echoed as a final answer
- not_established: value of array guidance on genuine array tasks
- consequence: array_guidance off in "1b" and in measured harness policy
- redundant: none
- supersedes: none
- next: none

### CON-015 — Refusing cosmetic restatements did not convert them into substantive edits
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-20, EXP-21
- contradicted_by: none
- scope: Qwen, dev split, the 2 restatement tasks only, single temperature-0 run
- establishes: after the neutral refusal, both trajectories ended with `done` claiming a fix, in the same round as control; no retry, read or diagnosis; hidden-test passes on these tasks 0 → 0; the lane escalated (no false verification). EXP-21: with that completion also blocked, both tasks repeated `done` and escalated (CON-016)
- not_established: that Qwen generally ignores tool feedback (n=2); whether a different refusal content or a retry budget would change the next action (not tested; would be a separate factor)
- consequence: superficial restatement is real but is not the dominant completion bottleneck on dev; completion claims in these trajectories did not depend on the edit result
- redundant: further no-op detection refinements under the same refusal text and loop policy
- supersedes: none
- next: Q-002

### CON-016 — Qwen did not show adaptive recovery under enforced mutation feedback in this dev experiment
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-21
- contradicted_by: none
- scope: Qwen, dev split, qwen_astnoop base with the completion latch, single temperature-0 run, 8 blocked trajectories
- establishes: the latch refused all 8 completion attempts made after an unapplied mutation (MI held); in 8/8 the next model output was an identical second `done` (re-engagement 0, recovery R 0) and every blocked task escalated; passes 3 → 3 (same pass set); damage and false verification 0; +8 rounds, +13.6k prompt tokens
- not_established: that Qwen cannot use mutation feedback under any content, prompt or retry policy (only a neutral completion check was tested); behavior of other models; heldout behavior
- consequence: enforcing completion state converts false completion trajectories into escalations but does not produce recovery. Control-flow gating alone is not the completion lever for this model and stack.
- redundant: further completion-gate variants that differ only in the gating rule, with the same neutral message
- supersedes: none
- next: Q-002

### CON-017 — An explicit type-specific replacement-format contract did not increase structurally valid replacement proposals in this dev experiment
- status: SUPPORTED
- confidence: dev-supported
- evidence: EXP-22
- contradicted_by: none
- scope: Qwen, dev split, qwen_selectorkind base with the replacement-format contract text only, single temperature-0 run, 16 solvable tasks
- establishes: the contract was delivered in 20/20 treatment rows and absent in 20/20 drift rows (MI held); solvable tasks with at least one structurally valid proposal 7 → 7 (frozen F threshold 9 not met); format-invalid solvable proposals 4 → 5; passes 3 → 3; validity and safety held; 0 format-invalid proposals executed
- not_established: the effect of other contract wordings, examples, constrained decoding or repair; that individual task swaps (e.g. +config_database_host, -inventory_total_value) are effects; what dominates replacement correctness; heldout behavior
- consequence: stating the replacement format explicitly before the edit is not, by itself, a lever for structural validity on this model and stack; replacement_format_contract stays available and off by default
- redundant: contract-text variants that only restate the same structural rules
- supersedes: none
- next: Q-002

## Methodology

### METH-001 — Validate the harness boundary before attributing behavior to the model
- status: SUPPORTED
- evidence: EXP-13, FND-02, FND-03, MNT-01
- contradicted_by: none
- scope: all model-behavior claims
- establishes: two apparent model behaviors were harness-induced (200-char read truncation; false completion notice); re-read delivery was verified before the Gemma re-read loop was attributed to the model
- not_established: that no further harness confounds exist
- consequence: before a behavioral conclusion, verify what the model actually received at the loop and adapter boundaries
- redundant: none
- supersedes: none
- next: none

### METH-002 — Infrastructure repairs stay outside treatment arms
- status: SUPPORTED
- evidence: MNT-01, EXP-13
- contradicted_by: none
- scope: harness defects discovered mid-program
- establishes: repairing the duplicate-read notice changed Gemma's distribution (model-originated premature done 6/16→0/16); a repaired baseline was required before designing the next treatment
- not_established: none
- consequence: repair, add regression tests, freeze a new harness hash, rerun the control only, then design
- redundant: none
- supersedes: none
- next: none

### METH-003 — Freeze gate and scorer by hash before inspection; pair structurally; score once
- status: SUPPORTED
- evidence: EXP-15, EXP-16, EXP-17, EXP-18
- contradicted_by: none
- scope: all frozen-gate experiments
- establishes: scorer changes happened only before inspection, with both hashes logged; positional pairing with hard failure produced 0 pairing errors across four gates; dry checks on frozen controls reproduced known values
- not_established: none
- consequence: new gates need a pre-run scorer hash, a dry check on frozen control only, and a single run
- redundant: none
- supersedes: none
- next: none

### METH-004 — Temperature-0 drift reruns reproduce frozen controls
- status: SUPPORTED
- evidence: EXP-14, EXP-16, EXP-17, EXP-18
- contradicted_by: none
- scope: this harness family, dev split, temperature 0
- establishes: every drift rerun stayed within its pre-registered tolerance; identical on every scored field in EXP-17, with small differences elsewhere (EXP-16 damaged 0 vs control 1; EXP-18 escalations 14/6 vs 13/7)
- not_established: stability at nonzero temperature or on heldout
- consequence: drift reruns stay as a cheap validity check; they are never the inferential control
- redundant: none
- supersedes: none
- next: none

### METH-005 — Evidence-hit metrics need a localization cap
- status: SUPPORTED
- evidence: EXP-12, EXP-15, FND-05
- contradicted_by: none
- scope: any quote- or span-based evidence metric
- qualification: EXP-12 ran under FND-03; the whole-file span width of accepted quotes is a property of the quote text, independent of that confound
- establishes: both accepted diagnose_v1 quotes spanned the whole file and trivially "hit" the defect
- not_established: none
- consequence: hits count only if span ≤ max(3, file_lines // 4)
- redundant: none
- supersedes: none
- next: none

### METH-006 — Per-stage funnels locate break points that aggregate metrics hide
- status: SUPPORTED
- evidence: EXP-17, EXP-18
- contradicted_by: none
- scope: repair pipelines
- establishes: the EXP-17 loss sat entirely at "edit executed" (7→2); EXP-18 moved it to replacement quality
- not_established: none
- consequence: every repair gate reports the cumulative funnel and the diagnostic cohort
- redundant: none
- supersedes: none
- next: none

### METH-007 — Long background batches are killed under memory pressure; foreground batches with unload complete
- status: SUPPORTED
- evidence: EXP-12, EXP-17, EXP-22, MNT-06
- contradicted_by: none
- scope: 5.3 GB RAM laptop, qwen2.5-coder:1.5b via local Ollama 0.34 (one loaded model, one parallel slot), Claude Code background-task monitor
- qualification: EXP-12's FND-03 confound concerns model behavior, not process memory
- establishes: background batches were killed three times across EXP-12 and EXP-17; foreground batches of 4 with model unload completed without kills; checkpointed rows were never corrupted. Warm sequential execution (resident model, independent task state) was validated: about 31 s vs 52 s per task, cold/warm byte-identical on 2/2 control tasks, and the EXP-22 drift arm (warm batches of 5 and 2) reproduced the frozen control's trajectories on 20/20 tasks. On this laptop under the observed workload, a 5-task invocation ended at 99.5 MB available RAM, while batch size 2 kept 243–648 MB
- not_established: that batch size 2 is globally or intrinsically optimal; behavior on other machines, models or workloads
- consequence: run in the foreground with warm sequential invocations; batch size 2 is the currently validated operating point on this laptop under the observed Qwen/Ollama workload, batch size 1 is the pressure fallback; no concurrency; resume from checkpoints
- redundant: none
- supersedes: none
- next: none

### METH-008 — Compact-mode compression once fabricated content; earlier compact numbers are not comparable
- status: SUPPORTED
- evidence: EXP-04, FND-01
- contradicted_by: none
- scope: measurements before the compression fix
- establishes: file contents were rewritten with a fabricated "status" key before the fix
- not_established: none
- consequence: quantitative comparisons use only post-fix runs
- redundant: none
- supersedes: none
- next: none

### METH-009 — The committed oracle is public; final heldout evaluation needs a private oracle boundary
- status: SUPPORTED
- evidence: MNT-05, EXP-19
- contradicted_by: none
- scope: all evaluations after 2026-09-14 publication of zowskyy/cordiforever (public)
- establishes: benchmark/oracle/ and result rows containing oracle tracebacks are in public git history; completed experiments (EXP-01…EXP-19) ran with models that had no network access, so their verdicts are unaffected
- not_established: that any model has been exposed to the oracle; that the existing heldout split is invalid for local models without network access
- consequence: treat the existing oracle as published. A future final heldout evaluation uses a separate private oracle that never enters public git history; keep the public development corpus distinct from it. Do not rewrite history to remove the published oracle.
- redundant: none
- supersedes: none
- next: none

### METH-010 — Byte-exact storage is required for hash-referenced evidence
- status: SUPPORTED
- evidence: MNT-05
- contradicted_by: none
- scope: git storage of gates, scorers, results, corpus and research documents on Windows
- establishes: core.autocrlf rewrote 36 CRLF evidence files on commit (4/10 logged hashes matched stored blobs); with `.gitattributes` `* -text` all 10 matched, and harness/corpus hashes were identical on Linux CI
- not_established: none
- consequence: keep `* -text`; CI integrity fails if it is removed; the evidence point is tag publish-byte-exact-2026-09-14
- redundant: none
- supersedes: none
- next: none
## Hypotheses

### H-001 — Offering the repository index as optional tools improves localization
- status: FALSIFIED
- confidence: dev-supported
- closed_by: EXP-08
- evidence: EXP-08
- contradicted_by: none
- scope: constrained actions, both models
- qualification: FND-02 and FND-03 present; the falsifying observation is tool non-adoption
- establishes: pre-registered improvement rules not met; non-adoption observed
- not_established: none
- consequence: see CON-001
- redundant: see CON-001
- supersedes: none
- next: none

### H-002 — Deterministic targeted grounding improves localization
- status: SUPPORTED
- confidence: dev-supported
- closed_by: EXP-09
- evidence: EXP-09
- contradicted_by: none
- scope: localization-only corpus
- qualification: FND-02 and FND-03 constant across arms
- establishes: see CAP-003
- not_established: end-to-end benefit
- consequence: see CAP-003
- redundant: see CAP-003
- supersedes: none
- next: none

### H-003 — Localization is the end-to-end bottleneck
- status: FALSIFIED
- confidence: dev-supported
- closed_by: EXP-11
- evidence: EXP-11
- contradicted_by: none
- scope: this corpus, pre-extraction harness
- qualification: FND-02 and FND-03 constant across arms
- establishes: localization rose, hidden-test success stayed 0
- not_established: that localization is irrelevant in combination
- consequence: see CON-002
- redundant: see CON-002
- supersedes: none
- next: none

### H-004 — After grounding, semantic interpretation/editing is the bottleneck
- status: SUPERSEDED
- superseded_by: H-008, H-009, H-010
- evidence: EXP-11, EXP-12
- contradicted_by: EXP-12
- scope: post-L1 analysis
- qualification: EXP-11's cause classification predates FND-02 and FND-03
- establishes: EXP-11 cause 6 dominated; EXP-12 forensics placed failures before the edit step (no checkable diagnosis)
- not_established: a single semantic bottleneck
- consequence: the chain was split into evidence production (H-008, H-009) and edit execution (H-010)
- redundant: none
- supersedes: none
- next: none

### H-005 — Diagnose-before-mutation with model quotes improves repair
- status: FALSIFIED
- confidence: dev-supported
- closed_by: EXP-12
- evidence: EXP-12
- contradicted_by: none
- scope: both models
- qualification: FND-03 present; the non-adoption and quote failures are unaffected
- establishes: see CON-003
- not_established: none
- consequence: see CON-003
- redundant: see CON-003
- supersedes: none
- next: none

### H-006 — Gemma's premature completion is model-originated
- status: FALSIFIED
- confidence: dev-supported
- closed_by: EXP-13
- evidence: EXP-13, FND-03, MNT-01
- contradicted_by: none
- scope: gemma3:1b, dev corpus
- establishes: model-originated done without mutation 6/16→0/16 after the notice repair
- not_established: none
- consequence: done-without-mutation guards have no supporting evidence
- redundant: premature-completion interventions for Gemma under the repaired harness
- supersedes: none
- next: none

### H-007 — Fact-only recovery messages change Gemma's progression
- status: FALSIFIED
- confidence: dev-supported
- closed_by: EXP-14
- evidence: EXP-14
- contradicted_by: none
- scope: repaired harness
- establishes: see CON-004
- not_established: none
- consequence: see CON-004
- redundant: see CON-004
- supersedes: none
- next: none

### H-008 — Qwen's quote failures are caused by diagnosing before reading
- status: FALSIFIED
- confidence: dev-supported
- closed_by: EXP-15
- evidence: EXP-15
- contradicted_by: none
- scope: Qwen, full reads
- establishes: ordering fixed (14→0) with no localized-hit change; 7/7 post-read re-diagnoses invalid
- not_established: none
- consequence: see CON-005
- redundant: see CON-005
- supersedes: none
- next: none

### H-009 — Model-authored verbatim evidence was Qwen's localization bottleneck
- status: SUPPORTED
- confidence: dev-supported
- closed_by: EXP-16
- evidence: EXP-16
- contradicted_by: none
- scope: Qwen, exact selectors, read snapshot
- establishes: see CAP-004
- not_established: promotability (the gate FAILED on damage)
- consequence: see CAP-004
- redundant: see CAP-004
- supersedes: none
- next: none

### H-010 — Full-file rewriting is the damage mechanism after correct localization
- status: SUPPORTED
- confidence: dev-supported
- closed_by: EXP-17
- evidence: EXP-16, EXP-17
- contradicted_by: none
- scope: Qwen
- establishes: 5/5 damages via full writes (FND-04); bounded edits produced 0 damage
- not_established: that bounded edits alone preserve completion
- consequence: see CAP-005, CON-006
- redundant: see CON-006
- supersedes: none
- next: none

### H-011 — A single mixed selector field blocks bounded-edit execution; explicit kinds restore it
- status: PARTIALLY_SUPPORTED
- confidence: dev-supported
- evidence: EXP-17, EXP-18, EXP-19
- contradicted_by: EXP-19 (execution-gain threshold not met on heldout)
- scope: Qwen, dev split, single run
- establishes: the representation error and its removal by explicit kinds both appear on dev and heldout (syntax); the dev execution restoration was not confirmed on heldout by the pre-registered threshold
- not_established: that explicit kinds alone restore execution beyond dev; stability
- consequence: see CAP-006
- redundant: see CON-007
- supersedes: none
- next: Q-001

### H-012 — With selectors repaired, replacement quality is the next bottleneck
- status: OPEN
- evidence: EXP-18, EXP-19, EXP-20, EXP-21, EXP-22
- contradicted_by: none
- scope: Qwen, bounded edits with explicit kinds
- establishes: descriptive only. Dev (EXP-18): wrong_edit_choice 3, whole-file content as a symbol replacement 1, Python-literal JSON value 1. Heldout (EXP-19): with syntax 15/15 valid, replacement failures clobbering existing names 2, identical replacement 2, replacement breaking the file 2, executed-but-not-passing 3. Dev (EXP-20, PARTIAL): removing accepted structural no-ops (2 → 0) left completion unchanged (3 → 3), so restatement is not the dominant replacement-quality failure on dev. Dev (EXP-21, PARTIAL b): blocking completion after an unapplied mutation produced no retry (0/8 re-engaged), so completion gating does not surface better replacements either. Dev (EXP-22, PARTIAL b): an explicit type-specific format contract before the edit did not increase structurally valid proposals (VALID tasks 7 → 7). EXP-19 through EXP-22 weaken or eliminate specific explanations and interventions (selector representation, cosmetic restatement, completion gating after the edit, a format contract before the edit); they do not establish which remaining category dominates
- not_established: the dominant failure mode (semantic reasoning, algorithm generation, diagnosis or any other category), or any completion-improving intervention
- consequence: the next Qwen repair factor should target replacement content, not selectors
- redundant: none
- supersedes: none
- next: Q-002

### H-013 — Gemma's stalls are a control problem addressable by action masking
- status: OPEN
- evidence: EXP-14
- contradicted_by: none
- scope: gemma3:1b, repaired harness
- establishes: motivation only: text feedback failed (CON-004)
- not_established: any masking effect
- consequence: deferred as a coordinator-control experiment
- redundant: none
- supersedes: none
- next: Q-004

### H-014 — Edits on insufficient-evidence tasks need an explicit abstention mechanism
- status: OPEN
- evidence: EXP-16, EXP-18, EXP-19
- contradicted_by: none
- scope: Qwen
- establishes: category-3 edits persisted (EXP-16: 2 with damage; EXP-18: 1 without damage; EXP-19 heldout: T 1 without damage, reference 2 with 1 damaged; lanes escalated)
- not_established: that bounded edits make abstention unnecessary; any abstention mechanism's effect
- consequence: queued after the edit-reliability questions
- redundant: none
- supersedes: none
- next: Q-003

## Open questions

### Q-001 — Does the qwen_selectorkind_v1 PASS replicate on the heldout split?
- status: CLOSED
- derived_from: CAP-006, EXP-18
- evidence: EXP-18, EXP-19
- contradicted_by: none
- scope: identical conditions, heldout split
- establishes: answered by EXP-19: PARTIAL (b). Outcome clauses (safety, damage, completion ≥ reference) replicated at a near-floor completion level; the mechanism's execution gain did not reach its threshold
- not_established: n/a
- consequence: required before any preset change
- redundant: none
- supersedes: none
- next: none

### Q-002 — Which replacement-quality failure dominates after selector repair, and what single bounded factor addresses it?
- status: OPEN
- derived_from: H-012, EXP-18
- evidence: EXP-18, EXP-20, EXP-21, EXP-22
- contradicted_by: none
- scope: Qwen, bounded edits with explicit selector kinds
- establishes: candidate modes observed (dev EXP-18 classification: correct 3, cosmetic restatement 2, incomplete fix 1, wrong target 1, whole-file-as-symbol 1, malformed JSON value 1, guard refusal 1); EXP-20 eliminated restatement acceptance without a completion gain (CAP-009, CON-015); EXP-21 showed post-edit feedback enforced as completion state did not produce a retry (CON-016); EXP-22 showed a pre-edit type-specific format contract did not increase structurally valid proposals (CON-017)
- not_established: the dominant remaining cause; no category (semantic reasoning, algorithm generation, diagnosis or other) is established
- consequence: the next stage is an offline first-failure taxonomy over frozen evidence (a diagnostic analysis, not an experiment and not EXP-23) before designing any treatment
- redundant: none
- supersedes: none
- next: none

### Q-003 — Can a deterministic rule stop edits on insufficient-evidence tasks without suppressing solvable edits?
- status: OPEN
- derived_from: H-014, FND-04, EXP-18
- evidence: EXP-16, EXP-18
- contradicted_by: none
- scope: Qwen
- establishes: category 3 persists at low counts
- not_established: n/a
- consequence: separate intervention after edit reliability
- redundant: none
- supersedes: none
- next: none

### Q-004 — Does deterministic action masking convert Gemma's stalled trajectories into exploration or edits?
- status: DEFERRED
- derived_from: H-013, CON-004, EXP-14
- evidence: EXP-14
- contradicted_by: none
- scope: gemma3:1b; framed as a coordinator-control experiment
- establishes: displaced-action outcomes must be pre-registered (new exploration / edit opportunity / different invalid action / oscillation / escalation)
- not_established: n/a
- consequence: not scheduled
- redundant: none
- supersedes: none
- next: none

### Q-005 — Do the unresolved selector cases (root-array JSON, non-pointer JSON targets, expression targets) limit coverage?
- status: DEFERRED
- derived_from: CAP-004, EXP-16
- evidence: EXP-16
- contradicted_by: none
- scope: Qwen extraction selectors
- establishes: 4 no-span failures in EXP-16 of those kinds
- not_established: n/a
- consequence: deferred so selector changes are not combined with edit changes
- redundant: none
- supersedes: none
- next: none

## Active research state
- open_hypotheses: H-012, H-013, H-014
- partially_supported_pending_replication: H-011, CAP-004, CAP-006
- open_questions: Q-002, Q-003
- active_experiment: none (next stage: offline first-failure taxonomy over frozen evidence; diagnosis, not an experiment)
- deferred_questions: Q-004, Q-005

## Research deltas

### Delta EXP-18
- BEFORE: Bounded edits removed damage (CAP-005), but completion fell because Qwen wrote Python targets in JSON-pointer form (CON-007); the selector-kind explanation (H-011) was untested.
- RESULT: qwen_selectorkind_v1 PASS (frozen scorer 135a71f9…): damaged 0 ≤ 2; hidden-test passes 3 ≥ 3; all guardrails; valid.
- LEARNED: With an explicit selector kind, Qwen's edit targets are syntactically valid (13/13) and bounded edits execute (2→6) without damage.
- NOT LEARNED: That the effect is stable (boundary pass, one dev run), that it holds on heldout, or that executed edits are correct.
- UPDATED: CAP-006 (new), H-011 PARTIALLY_SUPPORTED, H-012 (new, OPEN), H-014 (evidence added), Q-001, Q-002, Q-003 (new).
- SYSTEM CONSEQUENCE: Action schemas state selector kinds explicitly; no preset change before heldout replication; the next repair factor targets replacement content.
- ELIMINATED WORK: Mixed-field selector interfaces; normalization of `/name` targets; further selector-representation variants under equivalent conditions.
- NEXT UNCERTAINTY: Q-001 (replication) and Q-002 (dominant replacement failure).

### Delta EXP-19
- BEFORE: The qwen_selectorkind stack passed on dev at the completion bound (CAP-006, dev-supported); replication was untested (Q-001).
- RESULT: qwen_selectorkind_heldout_v1 PARTIAL (b) under the frozen scorer: validity and safety held; M failed (edit-executed gain +2 < 3, syntax 15/15); P1h held (damage 0 ≤ reference 4); P2h held (passes 1 ≥ reference 1).
- LEARNED: On untouched tasks the bounded-edit stack keeps damage at 0 and false verification at 0 (CAP-005 and CAP-002 heldout-supported). The mixed-field selector error recurs in the control (5/10) and explicit kinds remove it (15/15), but valid selectors are then mostly lost to replacement-content failures.
- NOT LEARNED: That explicit selector kinds generalize as an execution fix (M failed); any heldout completion gain (1/16 equals the reference); that the single-agent path is competent enough for coordination research; causal attribution for the two new heldout-only failure modes.
- UPDATED: CAP-002 → heldout-supported; CAP-005 → heldout-supported; CAP-006 contradicted_by EXP-19, stays dev-supported; CON-007 heldout descriptive note; H-011 contradicted in part; H-012 evidence extended; H-014 evidence extended; Q-001 CLOSED.
- SYSTEM CONSEQUENCE: No preset change. Bounded edits with explicit selector kinds remain the Qwen experimental base. Replacement-content correctness (Q-002) is the next dev factor, designed without heldout task specifics. Coordination stays frozen.
- ELIMINATED WORK: Further heldout reruns of this stack under the same conditions; selector-representation variants; tuning on heldout failure modes.
- NEXT UNCERTAINTY: Q-002: which single change to the replacement-content contract turns syntactically valid bounded edits into correct, non-no-op, non-clobbering replacements.

### Audit EXP-19
- DIRECTION: checked: damage R 4 → T 0 (decrease), syntax C 5/10 → T 15/15 (increase), edit-executed gain +2 (below threshold), passes T 1 vs R 1 (equal); all records state these directions.
- POPULATION: checked: heldout split, 20 tasks per arm, 16 solvable; edit-level rates use edit calls as denominator (C 10, T 15); funnel counts are cumulative over solvable tasks; dev numbers are labeled dev.
- COMPARISONS: checked: heldout R/C/T are compared only to each other; dev values appear only as labeled context; no drift arm exists in this gate; CAP-006's dev comparison (frozen qwen_localedit) is not mixed with heldout C.
- DESCRIPTIVE VS GATE: checked: CAP-002 and CAP-005 promotions rest on gated clauses S and P1h for T; C's 0 damage and 5/10 syntax, failure modes and the pass trace are marked descriptive.
- CONFOUNDS: checked: no confounds registered for EXP-19; foreground-timeout continuations were the same checkpointed command and are recorded as transient.
- CAUSAL LANGUAGE: checked: "valid selectors mostly lost to replacement-content failures" is stated as an observed distribution, not a proven cause; the new heldout-only modes carry no causal claim.
- NARROW FINDINGS: checked: the M failure does not erase the gated safety and damage replication, which is recorded (CAP-002, CAP-005).
- NARROW PASS: checked: PARTIAL (b) is not represented as generalized capability; milestones (1)–(3) are recorded as not claimed; completion is described as near floor.

### Delta EXP-20
- BEFORE: With selectors repaired (CAP-006, dev-supported), dev replacement failures included 2 accepted cosmetic restatements (quote changes only); whether refusing them would raise completion was untested (H-012, Q-002).
- RESULT: qwen_astnoop_v1 PARTIAL under the frozen scorer (ef5492b9…): validity held (drift identical to control on 20/20 trajectories); MI held (accepted structural no-ops 0); safety held; capability NO_IMPROVEMENT (passes 3 = control 3).
- LEARNED: A deterministic structural no-op detector refuses exactly the restatement edits without touching any other trajectory (CAP-009, mechanism-valid). In both refused trajectories the model then claimed completion anyway, in the same round as control (CON-015, n=2).
- NOT LEARNED: Any completion gain; whether different refusal content or a retry policy would change behavior after a refusal; the dominant remaining replacement failure; anything about heldout.
- UPDATED: CAP-009 (new, mechanism-valid); CON-015 (new, dev-supported); H-012 evidence extended; Q-002 evidence extended (stays OPEN).
- SYSTEM CONSEQUENCE: No preset change. `ast_noop_refusal` stays available and off by default. Restatement refusal is not the completion lever; the queued format-contract and semantic-content factors remain candidates for Q-002.
- ELIMINATED WORK: Broader no-op equivalence notions (folding, renaming, unparse normalization) under the same refusal and loop policy; heldout replication of this mechanism for completion purposes.
- NEXT UNCERTAINTY: Q-002: which single factor addresses incomplete or wrong-target replacements, or whether completion claims issued independently of edit results need to be addressed first.

### Audit EXP-20
- DIRECTION: checked: accepted no-ops 2 → 0 (decrease); passes 3 → 3 (no change); cumulative edit executed 6 → 4 (decrease, explained as the removed no-ops); extended-funnel executed 5 → 5; damage 0 → 0.
- POPULATION: checked: dev split, 20 tasks per arm, 16 solvable; CON-015 is scoped to the 2 restatement tasks; counts are tasks except no-op counts, which are edit calls (1 per task here).
- COMPARISONS: checked: inferential comparison is treatment vs frozen control only; drift is validity only; no heldout values are used.
- DESCRIPTIVE VS GATE: checked: CAP-009 rests on gated MI and S clauses; the unchanged next action, round equality and trajectory identity are descriptive; the scorer's `next_action` field is recorded as mislabeled (`none` for `done`) and not used.
- CONFOUNDS: checked: no confounds registered; the batch timeout, memory kill and one-task-per-call execution are transient, and the rows are checkpointed with identical provenance.
- CAUSAL LANGUAGE: checked: CON-015 states that completion claims in these 2 trajectories did not depend on the edit result, not that Qwen ignores feedback in general; "not the dominant bottleneck" is limited to dev completion.
- NARROW FINDINGS: checked: NO_IMPROVEMENT does not erase the mechanism result, which is recorded as CAP-009 at mechanism-valid.
- NARROW PASS: checked: PARTIAL is not described as a capability gain; confidence for CAP-009 is mechanism-valid, not dev-supported.

### Delta EXP-21
- BEFORE: In EXP-20 both refused restatements were followed by `done` in the same round as control (CON-015); whether enforcing the mutation result as completion state would produce recovery was untested (Q-002).
- RESULT: qwen_donelatch_v1 PARTIAL (b) under the frozen scorer (0e077536…): validity held (drift identical to control on 20/20 trajectories); MI held; safety held; capability NO_IMPROVEMENT (passes 3 = control 3); recovery R 0 < 2.
- LEARNED: The latch refused all 8 completion attempts made after an unapplied mutation, and in 8/8 the model's next output was an identical second `done`; every blocked task escalated (CON-016). Completion gating turns false completion trajectories into escalations without eliciting a retry.
- NOT LEARNED: Whether different completion-check content, a retry budget, or a prompt-level change would alter the next action; anything about other models or heldout; the dominant replacement failure.
- UPDATED: CON-016 (new, dev-supported); CON-015 evidence extended; H-012 evidence extended; Q-002 evidence extended (stays OPEN).
- SYSTEM CONSEQUENCE: No preset change. `completion_requires_mutation_success` stays available and off by default. Post-edit feedback delivered through harness state did not change Qwen's plan in any observed trajectory, so the next Q-002 factor should act before or at edit proposal (e.g. the queued format contract) rather than after the edit result.
- ELIMINATED WORK: Completion-gate variants that differ only in the gating rule with the same neutral message; treating escalation counts as recovery evidence.
- NEXT UNCERTAINTY: Q-002: whether a pre-edit factor (replacement-format contract) improves replacement correctness when post-edit feedback is not used by the model.

### Audit EXP-21
- DIRECTION: checked: completions refused after an unapplied mutation 0 → 8; next action repeated done 8/8; re-engagement 0; R 0; passes 3 → 3; "no escalation" endings 12 → 5; rounds 139 → 147; prompt tokens +13.6k.
- POPULATION: checked: dev split, 20 tasks per arm, 16 solvable; the blocked population is 8 treatment tasks (7 pre-registered triggers plus `inventory_update_qty`); counts are tasks unless stated.
- COMPARISONS: checked: inferential comparison is treatment vs frozen EXP-20 treatment rows; drift is validity only; no heldout values are used.
- DESCRIPTIVE VS GATE: checked: CON-016 rests on gated R, MI, S and C; re-engagement, next actions, rounds, tokens and the two passing blocked tasks are descriptive; the scorer's `blocked_after_earlier_successful_edit` field is recorded as under-counting (it looks only before the first `set`) and is not used; the corrected value is from the traces.
- CONFOUNDS: checked: no confounds registered; the bounded lane still runs checks after an agent escalation (existing behavior), which explains `verified_done` for two escalated tasks whose correct edit was already applied; no pass is attributed to the latch.
- CAUSAL LANGUAGE: checked: CON-016 is limited to "did not show adaptive recovery under enforced mutation feedback in this dev experiment"; "the action after an edit appears fixed before its result is seen" is stated as an observed pattern, not a mechanism claim.
- NARROW FINDINGS: checked: PARTIAL (b) does not erase that the latch worked as specified (MI held) and removed accepted completions after unapplied mutations.
- NARROW PASS: checked: no capability gain is claimed; escalation is not counted as success; the flag stays off by default.

### Delta EXP-22
- BEFORE: With explicit selector kinds, 5 of 13 dev proposals violated a structural replacement format (all refused by existing guards); whether an explicit type-specific format contract shown before the edit would increase structurally valid proposals was untested (H-012, Q-002).
- RESULT: qwen_formatcontract_v1 PARTIAL (b) under the frozen scorer (7141c97c…): V held (drift identical to control 20/20); MI held (contract delivered 20/20, absent in drift 20/20, 0 pairing or structural-preservation violations); S held; F not improved (VALID tasks 7 < 9; FORMAT_INVALID 5 > 4); C NO_IMPROVEMENT (passes 3).
- LEARNED: This explicit type-specific replacement-format contract did not increase structurally valid replacement proposals in this dev experiment (CON-017).
- NOT LEARNED: Whether individual task swaps are effects; the effect of other wordings, examples, constrained decoding or repair; what dominates replacement correctness; anything about heldout.
- UPDATED: CON-017 (new, dev-supported); H-012 evidence extended (stays OPEN, not upgraded); Q-002 evidence extended (stays OPEN); METH-007 updated with machine-scoped execution evidence; MNT-06 (new, infrastructure).
- SYSTEM CONSEQUENCE: No preset change; `replacement_format_contract` stays available and off by default. The next stage is an offline first-failure taxonomy over frozen evidence: diagnosis, not EXP-23, not an experiment, with no inference. Execution: warm sequential invocations, batch 2 as this laptop's current default, batch 1 as the pressure fallback, no concurrency.
- ELIMINATED WORK: Contract-text variants that only restate the same structural rules; designing the next intervention before the first-failure taxonomy exists.
- NEXT UNCERTAINTY: Q-002: of the unsuccessful solvable trajectories, where is the first capability failure, and which mutually exclusive first-failure class is largest?

### Audit EXP-22
- DIRECTION: checked: VALID tasks 7 → 7 (no change); FORMAT_INVALID solvable proposals 4 → 5 (increase); passes 3 → 3; localized 8 → 9; per-call VALID rate 0.64 → 0.58; insufficient-evidence executed mutations 1 → 1.
- POPULATION: checked: dev split, 20 tasks per arm, 16 solvable; F uses solvable tasks (VALID) and solvable proposals (FORMAT_INVALID) with the frozen denominators; SELECTOR_FAILURE and UNCLASSIFIABLE were 0 in every arm.
- COMPARISONS: checked: inferential comparison is treatment vs the frozen EXP-18 control only; drift is validity only; no heldout values are used.
- DESCRIPTIVE VS GATE: checked: CON-017 rests on the gated F, V, MI and S clauses; task swaps, the reason distribution, per-call rates, the guard invariant and insufficient-evidence counts are descriptive and labelled as such.
- CONFOUNDS: checked: no confounds registered; the batch-size reduction (5 → 2) and port-3080 warnings are infrastructure events, and drift identity 20/20 shows no effect on model-visible behavior; the historical-truncation measurement asymmetry was bounded by the drift VALID-task check (0 difference).
- CAUSAL LANGUAGE: checked: CON-017 says "did not increase … in this dev experiment"; no claim that format is irrelevant, and no claim about which category dominates.
- NARROW FINDINGS: checked: PARTIAL (b) does not erase that the intervention was delivered as specified (MI) and that no format-invalid proposal executed.
- NARROW PASS: checked: no capability or format gain is claimed; H-012 and Q-002 are not upgraded; the 20/20 drift identity is recorded as execution methodology (METH-007, MNT-06), not EXP-22 evidence.
