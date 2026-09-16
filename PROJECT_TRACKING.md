# PROJECT_TRACKING — Cordi v2

Current truth only. History: `EXPERIMENT_LOG.md`. Enable/disable rationale: `DECISIONS.md`. Accumulated knowledge (CAP/CON/METH/H/Q): `RESEARCH_YIELD.md`. After every experiment: registry closure + Research Delta, then `scripts/validate_research_state.py` must pass before the next experiment is registered.

## Current decision state (2026-09-14)

```text
Production/default ("1b" preset, gemma3:1b):
- constrained text action protocol, temperature 0, num_predict 2048
- read-before-overwrite ON, repeat detection + typed escalation ON
- known-path guard ON, named-file read invariant ON
- grounding (L1) OFF, evidence completion gate (L2) OFF
- structured editing OFF, repo tools OFF, array hint OFF
- bounded task lane available, not used by the free-text CLI

Validated:
- protocol reliability: provisionally passed
- bounded-lane verification: passed on the current corpora (0 false verified)
- optional repo-tool exposure: no localization benefit (non-adoption)
- L1 targeted grounding: localization benefit demonstrated (dev, n=16), also end-to-end
- L1 end-to-end gate: FAILED (oracle 0/16 -> 0/16 both models; damaged-file tasks rose) -> not promoted
- localization is not the end-to-end bottleneck on this corpus

Unresolved:
- end-to-end task success (best so far 3/16 hidden-oracle passes: qwen_extract in qwen_extract_v1 and qwen_selectorkind
  in qwen_selectorkind_v1; single dev runs; see RESEARCH_YIELD CAP-004, CAP-006)
- semantic interpretation / edit quality (dominant failure cause under L1: 9/16 Gemma, 8/16 Qwen;
  classified before the 200-char confound and the duplicate-read harness defect were found)
- same-name distractor ambiguity (5/16 Gemma under L1)
- CONFOUND: compact reads show at most 200 chars; "read the gold file" != "saw the defect"
  (unchanged in production; controlled with full_read_views in diagnose_v1, gemma_progress_v1, qwen_evidence_v1)
- natural-language -> TaskSpec translation

GATE diagnose_v1 (earlier) - FAILED both models (oracle 0->0 Gemma, 0->1 Qwen; valid run).
Gemma never called diagnose; Qwen's quotes failed the evidence check 19/21.
Forensics: Gemma 0/10 opportunity->attempt (path loops 10, premature done 8 [harness-induced, see repair below], no uptake 2);
Qwen 2/21 valid quotes (17/19 refusals genuinely ungrounded); both accepted quotes = whole file
(defect-hit metric vacuous -> needs a span cap in any future design).
HARNESS DEFECT REPAIRED (maintenance, harness af9f8800f3b7): repeated reads no longer get
"completed ... Finish now". Earlier gate verdicts stand; premature-done claims from them are confounded.
REPAIRED GEMMA BASELINE (gemma_fullread): oracle 0/16; model-originated premature done 0/16;
existing-file re-read loops 10/20 and nonexistent-path loops 8/20 (both -> repeated_failed_call);
[superseded counts: as independent per-task read-loop flags, re-read 12/20, nonexistent-path read 5/20, both 1/20;
the 8 also counted repeated writes to missing paths]
edit opportunities 2/16. File content delivery on re-read turns verified.
COMPLETED GATE: gemma_progress_v1 - FAILED (edit opportunity 2/16 -> 2/16; valid, drift check 0).
26 fact-only recovery messages delivered; the next action after every one was the same read.
GEMMA FROZEN: textual recovery does not alter progression; action-masking deferred as a
coordinator-control experiment (not scheduled).
COMPLETED GATE: qwen_evidence_v1 - FAILED (valid; frozen scorer b309c179872b..., run once).
Localized hits 0->0; executed pre-read diagnoses 14->0 but valid 2/13; damaged 0->1.
After refusal + full read, 7/7 re-diagnoses still invalid: quote fidelity, not read order, limits Qwen.
COMPLETED GATE: qwen_extract_v1 - FAILED on damaged-file guardrail (5 > control 1); primary PASSED.
Localized-hit tasks 0 -> 8 (precision 0.82, spans <= 2 lines); hidden-test passes 1 -> 3; edit opportunities 9 -> 12.
Bottleneck moved downstream: of 8 localized-hit tasks, 3 pass, 4 mechanical_failure (3 damaged gold file), 1 wrong edit.
Damaged-case classification: category 1 (localized -> destructive rewrite) 3, category 3 (unsolvable -> edit) 2, category 2 among damaged 0.
COMPLETED GATE: qwen_localedit_v1 - FAILED on P2 (hidden-test passes 3 -> 1); P1 PASSED (damaged 5 -> 0).
Funnel break at "edit executed" (9 -> 2): 10/14 edits named Python symbols in JSON-pointer form (/divide).
Damage fell via refused rewrites and failed edits, not correct edits. Drift rerun reproduced control exactly.
Observed failure chain: localized hit -> edit opportunity -> malformed selector representation -> validator refusal
  -> no edit -> completion loss.
Not yet established: correct selector -> correct replacement -> hidden-test pass (replacement bodies already showed
  errors: unchanged `<`, wrong slugify, Python-literal JSON).
COMPLETED GATE: qwen_selectorkind_v1 - PASS (first gate pass). Selector syntax valid 4/14 -> 13/13;
edit executed 2 -> 6; hidden-test passes 1 -> 3 (at P2's bound); damaged 0; all guardrails held.
Caveats: single temp-0 dev run, n=16, boundary pass; heldout not run; no preset change made.
Established now: correct selector -> executed bounded edit (8/11 python_symbol edits succeeded, 0 damage).
Still not established: executed edit -> correct replacement -> pass (wrong_edit_choice 3; whole-file-as-symbol 1;
  JSON value syntax 1). Category 3 (edit on unsolvable task) persists: 1, no damage.
LAST COMPLETED GATE: qwen_formatcontract_v1.md - PARTIAL (b) on DEV (EXP-22): validity, MI and safety held; format not improved (VALID tasks 7 -> 7 < 9;
FORMAT_INVALID 4 -> 5); passes 3 -> 3. Contract delivered 20/20. CON-017 (dev-supported). replacement_format_contract available, off by default; no preset change.
Earlier: qwen_donelatch_v1 - PARTIAL (b) on DEV (EXP-21, CON-016); qwen_astnoop_v1 - PARTIAL on DEV (EXP-20, CAP-009, CON-015); qwen_selectorkind_heldout_v1 - PARTIAL (b) on HELDOUT.
Milestones (1)-(3) not claimed; coordination frozen. Q-002 open: no dominant replacement-correctness cause established.
Execution: warm sequential foreground invocations; batch 2 is this laptop's current default (batch 1 pressure fallback); no concurrency (METH-007, MNT-06).
NEXT GATE: none registered. Raw classification preserved (FND-06; methodology MNT-07). D3 construct review CLOSED by the D3-v2 methodology freeze (MNT-08): D3-v2 is frozen but has NOT been applied to real trajectories, so no D3 value, bottleneck label or funnel count has changed and the v1 classification stands unmodified. Real-data D3-v2 application is not authorized and needs its own plan. F0 forensics remain deferred; no new gate registered. Abstention (Q-003) separate.
Taxonomy applicability CLOSED by the MNT-09 amendment freeze: the frozen taxonomy may now be applied to a future arm only through an explicit, fail-closed Population Registration Record; heldout stays unconditionally rejected; MNT-07/MNT-08 are untouched and historical selection and classification are reproduced identically (classification at byte identity). MNT-09 registers no population but the historical one and admits no model arm.
Substrate qualification (EXP-SUBQ-01, Qwen2.5-Coder-1.5B incumbent vs MiniCPM5-2B challenger) is PLANNED ONLY and NOT registered; its S2 methodology phase is not implemented; no model has been downloaded or run.
Queue after this: abstention/unsolvable behavior (category 3), then broader coding capability. Gemma action-masking deferred.
```

## Research hypothesis
The primary blocker is no longer action syntax. Suspected chain: request → localization → semantic interpretation/edit → verification.
- Protocol encoding: mostly solved.
- Verification: can reject bad outcomes independently of the model.
- Localization: improved substantially with deterministic grounding.
- Tested 2026-09-14: better localization did NOT raise end-to-end success (0 → 0). Semantic interpretation/editing is now the isolated bottleneck.
  [Superseded as a current claim: later forensics (diagnose_v1) and gemma_progress_v1 located the failures before the edit step. Gemma does not progress from evidence to an edit attempt; Qwen does not produce file-grounded evidence. See EXPERIMENT_LOG "where the chain breaks" and the frozen Gemma conclusion.]

## Three separated concerns
| Concern | Question | What moved it |
|---|---|---|
| Capability | Can the model produce the right change? | L1 grounding (localization only so far) |
| Safety | Can deterministic guards prevent or expose bad changes? | path guard, read invariants, structured-edit policies: fewer stray/damaged files, success unchanged |
| Verification | Can the system establish the result independently? | bounded lane + hidden oracle: false completions became non-authoritative |

Assessment (judgment, not a measurement): protocol strong; guards strong; verification strong; localization materially improved; semantic editing weak; end-to-end autonomy not demonstrated.

## Earlier gate: end-to-end L1 — FAILED (full record in EXPERIMENT_LOG.md; not the most recent gate)
- Conditions: `{gemma,qwen}_constrained` rerun vs `{gemma,qwen}_L1` (+ `targeted_grounding` only; gate and repo tools off). Dev split, sequential, unload between conditions. Instrument: `benchmark/repo_task_eval.py`.
- Primary: `oracle_passed_solvable` must rise by ≥ 3 tasks per model (1–2 = noise).
- Must not regress: `lane_false_verified` = 0; `false_completion_on_insufficient_evidence` and `damaged_file_tasks` do not rise.
- Secondary (reported, not decisive): read recall/precision, gold first touch, mutation precision, gold edit recall, escalations, prompt tokens.
- Classified by the six causes: done (EXPERIMENT_LOG). Cause 4 vs 6 and the attempted paths behind refusals couldn't be separated: rows lack per-call arguments and rejected paths (evaluator gap).

## Priority stack
1. ~~Mechanical provenance on result rows; per-call arguments, rejected paths, read views, write diffs, model outputs~~ (done 2026-09-14).
2. ~~Repair `scripts/baseline_gate.ps1`~~ (done 2026-09-14; deterministic part verified, live part not).
3. ~~Pre-register, build, run `diagnose_v1`~~: FAILED.
   - ~~Forensic classification of Gemma replies and Qwen refused quotes~~ (done).
   - ~~Harness maintenance: duplicate-read notice repair; repaired Gemma baseline~~ (done).
   - ~~`gemma_progress_v1`~~: FAILED; Gemma conclusion frozen.
   - ~~`qwen_evidence_v1`~~: FAILED (scored once with frozen scorer).
   - Deferred, not scheduled: Gemma action-masking as a coordinator-control experiment, only after Qwen is diagnosed.
4. Re-test L2 when completion errors dominate.
5. Exhaustive transition tests over the real coordinator/loop/lane code (Hypothesis as a second layer).
6. Lean only if a concrete assurance gap remains that executable checks cannot close.

## Unresolved risks and open items (re-checked 2026-09-14 unless marked)
- `tests/test_run_command.py` timeout/workspace_cwd fail when bare `python` resolves to the Windows Store stub (environmental; present in the 2026-09-14 suite run).
- `scripts/swap_model.py` still writes `ModelPreset(...)` syntax that matches no real structure (presets are a dict in `core/calibration.py`).
- Qwen defaults remain in `web/client/lib/agent.ts:14`, the `web/sdk.py:106` session-metadata fallback, and the historical `scripts/measure_*` / `debug_*` scripts. Benchmarks, `ui.py`, `main.py` and `web/sdk.py create_session` default to gemma3:1b.
- `requirements.txt` pins `pytest>=8.0,<9`; the suite also runs on 9.1.1.
- Gemma calibration limits other than `max_tokens` mirror the 1.5b preset; not re-measured for Gemma's tokenizer.
- Hardware: 5.3 GB RAM; one model at a time; runs must be sequential with unload.
- Not re-checked since 2026-08-30: `tests/test_real_model.py` live tests answer via deterministic shortcuts (0 model calls) and `test_event_logging_with_real_model` fails under `--live`; embedding cache is plaintext; SemanticRouter costs tokens when enabled (full profile only).
- Heldout split never run.
- Resolved and removed from this list: `ui.py` undefined `WORKSPACE` (no occurrence in `ui.py`); "Gemma has no eval scores" (see EXPERIMENT_LOG).

## Architecture invariants (audit, still in force)
- All P0/P1 audit findings resolved (API key env-based, lite LLM routing gated, parser names, pruner defaults, linter dot-paths, `chat.py` deleted).
- Model-specific numbers live only in `core/calibration.py` `MODEL_PRESETS`; invariant layers read `calibration_from_context()`.
- Zero-token lite profile enforced at both LLM routing sites.
- Tool results truncate to `max_tool_result_bytes`; pruner is dual-metric; the loop never routes to another model (escalation is a typed outcome for the coordinator).

## File inventory (py file counts taken early 2026-09-14; STALE: not recounted after `core/diagnosis.py`, `benchmark/gates/`, `benchmark/scoring/` and new tests were added)
| Tree | Py files | Notes |
|---|---|---|
| `core/` | 41 | incl. `calibration`, `bounded_task`, `structured_edit`, `path_candidates`, `repo_index`, `grounding`, `outcomes` — complete |
| `plugins/agent/` | 12 | `loop.py`, `schema_router.py`, routers — complete |
| `plugins/core/` | 28 | plugins registered in `main.py` |
| `plugins/math/` | 9 | deterministic handlers |
| `plugins/model/` | 4 | `ollama` (text tool protocol, format, options) |
| `plugins/tools/` | 4 | `FileTools` incl. repo and structured-edit tools (gated) |
| `benchmark/` | 16 | eval instruments: `tool_call_eval`, `agent_task_eval`, `repo_tasks`, `repo_task_eval`, `protocol_probe_eval`, `localization_eval`, … plus `repos/` and `oracle/` corpora |
| `tests/` | 82 + 10 | top level + `failure_recovery/` |
| `scripts/` | 21 | measurement/debug scripts (several historical, qwen-default); `validate_skills.py` (complete) validates the skill registry |
| `skills/` | 7 + registry | reusable execution procedures (complete): `registry.yaml`; experiment-preregistration, experiment-execution, frozen-scorer, mutation-testing, research-closure, evidence-audit, ci-offload (`<id>/SKILL.md`) |
| root | `main.py`, `ui.py`, `conftest.py` | |

Open dependencies: none wired but unimplemented. Not built (by decision, not stubs): natural-language → TaskSpec translation, two-stage wildcard delete (`delete_batch` token), mastermind layer.

## Verification
- Execution planes (since 2026-09-14): LOCAL = model research (Ollama runs, frozen protocols, narrow tests for changed files); GITHUB ACTIONS = deterministic verification on every push (full pytest, research-state validator, frozen-evidence manifest/logged-hash/scorer-output/run-row checks, provenance). The full local baseline gate is run only when a protocol requires same-machine validation or to debug a Windows-vs-CI difference.
- Research state: `.venv\Scripts\python.exe scripts\validate_research_state.py` → OK (also in CI project-validation and inside baseline_gate.ps1).
- Skills: `.venv\Scripts\python.exe scripts\validate_skills.py` → `skills: OK (7 registered)` (also in CI project-validation; tests `tests/test_validate_skills.py`).
- Infrastructure queue (not scheduled; must not change experimental semantics): a consolidated human-readable CI run summary (commit, tests, validator, frozen evidence, logged hashes, duplicate runs, scorers executed, tracked-file mutations); Ruff/mypy baseline then ratchet; Node 20 action-version updates.
- Deterministic gate: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp %TEMP%\pytest_cordii` → 864 passed / 2 environmental / 8 skipped (2026-09-14).
- `powershell -File scripts/baseline_gate.ps1 -SkipLive` → `baseline=OK passed=864 skipped=8`. Requires research state OK and ≥ 864 passed and ≤ 8 skipped; fails on any failure outside the 2 allowlisted environmental ids (verified with a temporary failing test). Live section NOT VERIFIED.
- Lane-positive calibration milestone: first natural observation 2026-09-14 (qwen_diagnose `inventory_total_value`: lane verified_done, oracle pass; n=1). Still insufficient to estimate precision. Original note: the first natural `verified_done` runs must be checked against the oracle as a separate milestone. Current evidence covers only the failure path and the forced lying-verifier test.
- Use a writable `TEMP` basetemp; `C:\tmp` breaks under the sandbox.
- Live model runs are confirmatory and probabilistic; the benchmark JSONL files under `benchmark/results/` are the measurement record.
