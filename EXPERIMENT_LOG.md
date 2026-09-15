# EXPERIMENT_LOG — Cordi v2

Chronological lab notebook moved verbatim from PROJECT_TRACKING.md on 2026-09-14. Historical: statements here were true when written and may be superseded. Current state lives in PROJECT_TRACKING.md; enable/disable decisions live in DECISIONS.md.

## Milestone: gemma3:1b migration (2026-09-13)
- **Defaults switched** to `gemma3:1b`: `main.py --model`, `OllamaModel`, `ui.py`, `web/server.py`, `web/sdk.py create_session`, `run.ps1`, `scripts/setup.ps1`, `Modelfile`, `tests/test_real_model.py`.
- **Calibration:** new `"1b"` preset in `core/calibration.py` (previously `gemma3:1b` silently fell back to the qwen `1.5b` preset). Only `max_tokens` is measured; other limits mirror the 32k 1.5b preset — **not yet re-measured for Gemma's tokenizer**.
- **Adapter fix (`plugins/model/ollama.py`):** Ollama returns HTTP 400 "does not support tools" for gemma3; `raise_for_status()` dropped that body, so the fallback never fired and every tool-bearing turn crashed. Now: HTTP error bodies are surfaced; capability probed once via `/api/show` (cached); for non-tool models, `tools` is omitted, `role="tool"` messages become `user` turns prefixed `[tool result: name]` (gemma's template silently drops tool-role messages — proven by unchanged `prompt_eval_count`), and empty assistant turns carrying `tool_calls` are serialized as JSON content. Tests: `tests/test_ollama_model.py` (7).
- **Lite loop fix (`plugins/agent/loop.py`, model-independent, pre-existing):** lite requests are compiled from the event log, but verifier feedback, quarantine notes, repair, already-succeeded guidance and replan messages were only appended in memory, so every retry round sent a byte-identical request. They now also emit `user.message`/`system.message`.
- **Measured after fixes:** deterministic suite 591 passed / 2 failed (environmental, see below) / 8 skipped. Live multi-step probe ("read notes.txt, write line count to summary.txt", lite profile via `build_application`): both gemma3:1b and qwen2.5-coder:1.5b reach the model every round but never emit a tool call → max rounds (12). This is the model-proficiency baseline to improve next.

## Milestone: gemma3:1b proficiency pass 1 (2026-09-13)
Two evals (both run real Ollama, `temperature` 0 unless noted):
- `benchmark/tool_call_eval.py` (complete) — 30 single-turn tasks; is the first action the correct tool + path? Flags: `--prompt-file`, `--constrain`, `--temperature`, `--samples`.
- `benchmark/agent_task_eval.py` (complete) — 5 multi-step tasks through `main.build_application` lite; success is checked on the resulting files (`fix_bug` executes `add`). Flags: `--task`, `--trace`.

| gemma3:1b | first-step accuracy (30) | end-to-end (5) |
|---|---|---|
| start of session | 3.3% (default temp, old prompt/parser) | 0/5 (1 task probed) |
| after this pass | 86.7% (100% parseable) | 3/5 |

Reference: qwen2.5-coder:1.5b on the old production prompt = 3.3% first-step (10-task version).

Changes (each measured or unit-tested):
- `core/tool_call_extraction.py`: accepts bare `{"tool","args"}` / logical-name calls when a dispatcher schema (enum) is present. Tests: `tests/test_tool_call_extraction.py`.
- `plugins/agent/loop.py`: `LITE_COMPACT_GUIDANCE` constant rewritten (plain wording, flat JSON, read-before-edit rule, 3 examples); compact `done` returns its `summary`; duplicate-success guidance mentions `done` (constrained decoding cannot emit plain text); array guidance injected once instead of every round (flag was never reset); calibration-gated read-before-write guard that returns the file's contents instead of overwriting.
- `plugins/agent/schema_router.py`: `get_response_format()` (JSON schema for Ollama `format`), `done_summary()`.
- `plugins/model/ollama.py`: `options` and `response_format` (format sent only on tool-bearing turns).
- `core/calibration.py` `"1b"`: `sampling {temperature: 0}`, `constrained_actions`, `require_read_before_write`; wired in `main.py`.
- `plugins/agent/app_verifier.py`: app-type keywords matched as whole words and only with build intent or an app noun (was substring: "summary.txt" → calculator app, which derailed a finished task). Tests added in `tests/test_app_verifier.py`.
- `plugins/tools/file.py`: missing wildcard paths report matching workspace files (no deletion).
- Tests: `tests/test_gemma_wiring.py`. Suite: 613 passed / 2 environmental failures / 8 skipped.

Remaining failures (traced):
- `delete_logs`: at temperature 0 gemma repeats an identical failed call even when the error lists exact file names. Message-based fixes tried twice → next approach should change decoding (resample with higher temperature on a repeated failed call).
- `edit_config`: after being shown the full file, gemma still writes only `8080` (editing ability, not wiring).
- ArrayHelper relevance still substring-matches words like "add"/"delete" and injects irrelevant list guidance once per task.
- ~~Read-before-write guard is bypassable via `error_recovery` retry~~ — fixed in step 1 below.

## Proficiency phase 2 — step 1: read-before-overwrite invariant (2026-09-13)
- Enforced in `AgentLoop._execute_tool_call` (shared by the normal and `error_recovery` retry paths), before failure bookkeeping, so a rejection is not quarantined/counted as a tool failure (doing so made gemma paste the quarantine prose into `add.py`).
- Per-file content fingerprints (`_read_fingerprints`, sha256) instead of a global set: an overwrite is allowed only if the file's current fingerprint equals the one recorded when the model last saw it in full, or the agent wrote it. Unrelated writes do not invalidate; external edits do.
- A read counts only if nothing later hides part of it (tool-result pruner, `max_tool_result_bytes`, compact `compress_result`).
- A blind write is rejected with the full current contents (if ≤ `max_tool_result_bytes`); the identical call stays rejected for the rest of that round (blocks recovery retries) and is allowed once the model has had a turn.
- Tests (`tests/test_gemma_wiring.py`): blind overwrite, recovery-retry path, truncated read, external change, unrelated write, same write after seeing contents, default-off. Mutation check: disabling the guard fails 4 tests; treating every read as full fails the truncation test.
- Evidence: suite 618 passed / 2 environmental / 8 skipped; `agent_task_eval` gemma 3/5 (same tasks as before step 1).
- Found: in lite compact mode, `SchemaRouter.compress_result` shows the model only the first 200 chars of any read. Large files are effectively unreadable for gemma; relevant to step 4.
- Unfinished resampling code from before step 1 was removed (step 2 replaces it).

## Proficiency phase 2 — step 2: structural repeat detection + typed escalation (2026-09-13)
- Repeat key `tool:normalized_args@v<mutation_version>` (`AgentLoop._repeat_key`); `path` normalized (strip, `\`→`/`, leading `./`). Global `_mutation_version` increments on every successful `write_file`/`delete_file`.
- A key is recorded as failed only on a real tool failure inside `_execute_tool_call`. Guard refusals now raise `core.errors.PolicyRejection` before failure bookkeeping and are never recorded (otherwise the correct re-issued `fix_bug` write would be blocked).
- In a round, if any proposed call matches a failed key: it is not executed; the model is re-queried once with `temperature = repeat_retry_temperature` (0.4 for `"1b"`), then the model's options are restored. If the retry still proposes a failed key → `EscalationRequired` carrying `core.outcomes.EscalationOutcome` (reason, model, round, mutation_version, repeated_calls, retry_temperature, evidence). Models without `options` escalate immediately (`repeat_retry_unavailable`). The loop never selects another model; routing stays with the coordinator.
- Events: `repeat.detected`, `model.resampled`, `turn.escalated` (+ `turn.end` with `error: escalated`).
- Gated by calibration: presets without `repeat_retry_temperature` (qwen) keep previous behavior.
- Tests (`tests/test_gemma_wiring.py`, 6): no re-execution + 0.4 retry, typed escalation (incl. `./` path normalization), mutation makes the same call legitimate, policy rejection not counted, off without calibration, no-options escalation. Mutation check: disabling detection fails 3; dropping the version from the key fails the mutation test. The policy-rejection test is not covered by a mutation.
- Evidence: suite 624 passed / 2 environmental / 8 skipped. `agent_task_eval` gemma: 3/5 unchanged; `delete_logs` now ends in round 2 with a typed escalation (5.2 s) instead of 12 rounds (17 s); no repeats detected on the other tasks.
- `benchmark/agent_task_eval.py` now reports `repeats`, `resamples`, and the escalation outcome.

## Reliable tool-call emission (2026-09-13)
Metric: a reply counts only if it is exactly one executable action — `{"tool","args"}` with a known tool, all required args as strings, no extra args (`benchmark/action_validity.py`, tests in `tests/test_action_validity.py`). Truncated output counts as a failure.
- `SchemaRouter.get_response_format()` is now `anyOf` with one branch per logical tool (`const` tool name, `required` args, `additionalProperties: false`; `done` requires `summary`). Verified Ollama 0.34 enforces it: 0/10 violations on adversarial prompts with no system prompt at t=0 and t=0.8.
- Constrained decoding now applies in every profile: `constrained_actions` forces compact schema in `main.build_application`, and the loop uses `LITE_COMPACT_GUIDANCE` whenever compact mode is on (previously full profile got the verbose `tool_calls` prompt, mismatching the decoder).
- Runaway generation: reproduced 1/6 "Write the docs" samples at t=0.4 looping inside `content` (1024 tokens in 32.8 s; the earlier 120 s timeout ≈ 3.7k tokens). Fixes: `"1b"` sampling `num_predict: 2048`; `OllamaModel.last_done_reason` recorded for chat and stream; the loop treats `done_reason == "length"` as a failed emission — never executed or returned as an answer — retries once at `repeat_retry_temperature`, then raises `EscalationRequired(reason="truncated_output")`.
- Tests: per-branch schema, full-profile constraint, truncated→retry, truncated twice→escalation, adapter records done_reason. Mutation check: hiding `last_done_reason` from the loop fails both truncation-loop tests. Suite: 630 passed / 2 environmental / 8 skipped.

Measured (gemma3:1b, constrained):
| run | valid executable actions |
|---|---|
| single turn, t=0, 30 dev + 20 unseen probes | 30/30 dev, 20/20 probes |
| single turn, t=0.4 ×3, no output cap (old schema) | 90/90 dev, 59/60 probes (1 runaway timeout) |
| multi-step `agent_task_eval`, production settings | 18/18 model replies; task success 3/5 unchanged |

NOT VERIFIED: the t=0.4 ×3 emission run with `num_predict 2048` + anyOf schema (killed by the OS for low memory before output). Unconstrained baseline at t=0 also did not complete (120 s timeout).

> **Validity notice (2026-09-13):** every compact-mode measurement recorded above the "Structured editing" section — single-turn semantic baselines, the path-guard experiment, and the first grounding comparison — was taken while `SchemaRouter` fed the model fabricated JSON file contents (an injected `"status": "unknown"` key). Those numbers are **invalid for quantitative comparison** and kept only as a record of the failure mechanisms observed. The clean baseline is the four-condition run in "Structured editing" and later.

## Gate status (2026-09-13)
- **Tool-protocol reliability: provisionally passed.** Constrained gemma produced executable actions in 50/50 deterministic single-turn probes, 18/18 production multi-step replies, and 120/120 checkpointed dev samples below (t=0 and t=0.4 ×3, production cap). Runaway reproduced, bounded (`num_predict 2048`), fail-closed via truncation detection. The 150-sample probe confirmation is incomplete. Zero failures in n trials is not proof of 100% (n=150 → ~97.6% lower 95% bound).
- **Semantic execution reliability: failed / unresolved.** See below. Gemma is not authorized as an unrestricted autonomous implementer; target role is constrained proposer behind deterministic guards.

## Semantic action baseline (checkpointed, production settings: constrained anyOf, num_predict 2048)
`benchmark/tool_call_eval.py` rewritten: one JSONL row per sample in `benchmark/results/tool_call_eval.jsonl` (gitignored), keyed by a config hash (model, options, constraint, prompt/schema/task hashes); re-running resumes; `--max-new` bounds a batch; `--summary-only`. Categories: ok, wrong_tool, wrong_path, wrong_content, premature_done, missing_prerequisite_read (write on a modify-existing task), invalid_action, truncated, model_error. Single-turn cannot observe unnecessary actions, stale writes, or sequencing. Tests: `tests/test_tool_call_eval.py` (found and fixed: a partial last line from a killed process swallowed the next row).

| gemma3:1b, dev 30 tasks | t=0 ×1 | t=0.4 ×3 |
|---|---|---|
| executable action | 30/30 | 90/90 |
| semantic accuracy | 26/30 = 86.7% | 74/90 = 82.2% |
| missing_prerequisite_read | 2 | 6 |
| wrong_path | 1 | 5 |
| wrong_tool | 1 | 3 |
| wrong_content | 0 | 2 |
| premature_done / truncated / errors | 0 | 0 |

Notes: ordinary decisions already run at t=0; 0.4 is used only for the single retry after a repeated failed call or truncation. The largest category (missing_prerequisite_read) is already contained in production by the read-before-overwrite guard (write refused, contents shown).

## ui.py hygiene (2026-09-13)
- `ui.run_agent` now builds through `main.build_application` (lite) like the CLI and web SDK — same calibration, constraint, prompt, guards. Gradio imported lazily inside `create_ui`; removed undefined `WORKSPACE`; setup failures return `Error: ...` instead of raising NameError in `finally`.
- Tests: `tests/test_ui_entrypoint.py` (production settings observed at the model boundary; setup failure). Real run: `ui.run_agent("Create hello.py that prints Hello, World")` against Ollama gemma3:1b succeeded. NOT VERIFIED: Gradio page itself (gradio not installed in `.venv`).
- Suite: 642 passed / 2 environmental / 8 skipped.

## Wrong-path guard experiment (2026-09-13)
- `core/path_candidates.py` (complete): deterministic, narrow candidate matcher. `exact_basename` (same file name elsewhere) dominates; `near_name` requires same extension, stem ratio ≥ 0.85, stem length Δ ≤ 2 (so `app.test.json`/`adder.py` are not conflicts). `classify_path`: existing target → not this guard; missing + no candidate → allowed; missing + candidate → reads refused; writes refused unless authorized (exact_basename: only a full path containing a folder named in the request; near_name: path or file name named). Root-level duplicates of an existing name are refused (fail closed). Tests: `tests/test_path_candidates.py`.
- Guard `AgentLoop._enforce_known_path`, gated by calibration `require_known_paths` (NOT enabled in any preset). Runs before the overwrite guard (disjoint: missing vs existing targets). Refusal raises `PolicyRejection(reason="wrong_path", details={conflict, candidates})`, emits `guard.rejected` (all guards now emit it with reason codes `wrong_path`, `unread_overwrite`, `blind_write_retry`, `unshowable_overwrite`), and records the call as failed for repeat detection so a rejection loop escalates. `main.build_application(..., calibration_overrides=)` added for evals. Tests in `tests/test_gemma_wiring.py` (reject+candidates+no stray file, reject→repair, repeated wrong path escalates, explicit full-path duplicate allowed, off by default, overwrite guard precedence).
- `benchmark/agent_task_eval.py`: frozen 10-task corpus (original 5 + 4 path-sensitive + 1 control `create_named_duplicate`); per task `wrong_path_proposals` (same `classify_path` rule, split by conflict), `guard_rejections` (reason, conflict, path, candidates, round, retried, outcome repaired/repeated/unresolved), `stray_files`, rounds, tool calls; `--path-guard on|off`, `--label` → `benchmark/results/agent_task_eval_<label>.json`. Tests: `tests/test_agent_task_eval_metrics.py` (found: "repaired" originally required a path change, misclassifying unread_overwrite recoveries; fixed before the reported runs).

| gemma3:1b, frozen corpus, t=0, 1 run each | guard off | guard on |
|---|---|---|
| task success | 3/10 | 3/10 (identical tasks) |
| tasks with stray files | 4 | 0 |
| false "done" with wrong result | 4 | 0 (became typed escalations) |
| wrong-path proposals | 5 | 8 |
| wrong_path rejections repaired / repeated | — | 0 / 8 |
| unread_overwrite rejections repaired | 2/2 | 2/2 |
| rounds / tool calls | 31 / 16 | 31 / 19 |
| escalations | 2 | 6 |
| valid action rate | 100% | 100% |

Correction (recorded after the grounding experiment): the "false done" row above excluded `edit_config`, which ended with a false completion in every run. With the later mechanical definition (failed, no escalation, no error) the counts are **5 → 1**, not 4 → 0.

Conclusion: the guard is **defensive, not corrective** on this corpus — it removed all stray files and false completions without extra rounds, but Gemma repeated the refused path every time (even at the 0.4 retry) despite the candidate being in the error. The control task exposed a candidate-quality gap: Gemma wrote root `README.md` for "Create src/README.md"; the refusal (correct) suggested `docs/README.md` (the existing same-named file) rather than the path named in the request. Suite: 656 passed / 2 environmental / 8 skipped. Single run per configuration at t=0; not a variance estimate.

**Decision (2026-09-13):** `require_known_paths` enabled in the `"1b"` preset — **enabled for safety, not credited as a capability improvement** (task success unchanged at 3/10).

## Option A — request path grounding (2026-09-13)
- `core/path_candidates.request_path_refs` / `ground_request`: resolves only path/file-name tokens already in the request (must carry an extension). Reference exists → nothing. Missing with a folder → kept as requested; a line `X → new file at exactly X` only if the same file name exists elsewhere (never names the other file). Missing bare name → 0 candidates nothing, 1 `X → path`, >1 `X → ambiguous: a, b`. No workspace tree. Known limitation: a bare new root file whose name exists nested grounds to the existing file (same ambiguity the path guard refuses).
- Loop: calibration `ground_request_paths` (NOT enabled in any preset) appends one system message after the request and emits `request.grounded` (lines, chars). Tests: control acceptance (`Create src/README.md` → `src/README.md → new file at exactly src/README.md`, no `docs/README.md`), single/ambiguous/none/existing/escape, reaches the model in the lite envelope, off adds nothing.
- Dry run on the frozen corpus: no lines for the 5 original tasks; exactly the correct mapping for the 5 path tasks; no false matches.
- Eval additions (metadata only, corpus unchanged): `first_paths`, `first_path_correct`, `false_done` (failed with no escalation and no error), `grounding`, prompt tokens. Repair metric tightened after the traces: a wrong-path refusal is repaired only by success on an offered candidate (a read of an unrelated `count.txt` had been counted as repaired).

| frozen corpus, guard ON, t=0, 1 run each | ungrounded | grounded |
|---|---|---|
| task success | 3/10 | **4/10** (+create_named_duplicate) |
| first-attempt correct path (9 scored) | 4/9 | **8/9** |
| wrong-path proposals | 8 | 1 |
| wrong_path refusals (repaired/total, corrected metric) | 0/8 | 0/1 |
| unread_overwrite refusals repaired | 2/2 | 5/5 |
| escalations | 6 | 1 |
| **false done** | 1 | **4** |
| rounds / tool calls | 31 / 19 | 45 / 22 |
| prompt tokens total / first call (sum over tasks) | 18,629 / 3,827 | 28,976 / 3,963 (+136 for the 5 grounded tasks) |
| stray files / valid actions | 0 / 100% | 0 / 100% |

Traces of the new false completions (grounded): `nested_fix_bug` read the right file then rewrote the bug unchanged plus a prose line; `nested_config_port` was shown the full JSON by the overwrite guard and then **replaced `config/app.json` with `Port: 8080` (data destroyed)**; `nested_read_count` ignored the grounding, was refused, then wrote `10` to count.txt without reading. `nested_append` hit max rounds. Conclusion: grounding meets the stated adoption criterion (first-attempt path 4/9 → 8/9, success +1, no false matches) and moves the bottleneck to edit quality; it also converts honest escalations into false completions, including one destructive structured-file overwrite. Suite: 662 passed / 2 environmental / 8 skipped.

**Decision (2026-09-13):** grounding held (not in any preset). Stricter gate: enable only if grounded+structured shows no regression in destructive writes or false-done vs ungrounded+structured while materially improving first-attempt path or success.

## Structured editing (2026-09-13)
- `core/structured_edit.py` (complete): `replace_exact` (exactly one match; empty/no-op refused), `apply_json_patch` (RFC 6901 pointers, bare key = top-level; refuses root replacement, missing parents, type changes, past-end indices, absent removals), `serialize_like` (keeps indentation/trailing newline), `validate_language` (a .py that compiled must still compile; a .json that parsed must still parse). Tests: `tests/test_structured_edit.py` (20).
- `FileTools.replace_text` / `patch_json`: atomic temp-file replace, then re-read postcondition (file text equals intended text; JSON re-parses to the patched document); result text carries the change evidence. Schemas/handlers exposed only with calibration `structured_edits`.
- `SchemaRouter.STRUCTURED_TOOLS` (`replace`, `patch_json`) added to the logical tools, anyOf constraint, and expansions only when enabled; loop uses `LITE_COMPACT_GUIDANCE_STRUCTURED`.
- Policies with `structured_edits`: `overwrite_existing_file` (write_file only creates new files), `json_requires_patch` (no text replace on .json — observed `"port"`→`"8080"` renamed a key yet stayed valid JSON); both count toward repeat escalation. Read-before-write now also covers `replace_text`/`patch_json` (`unread_edit`) — observed: a short unique token like `"add"` matches without any knowledge of the file, so "exact match proves knowledge" was false. Path guard covers the edit tools.
- **Integrity bug found and fixed (pre-existing, affected every compact-mode run):** `SchemaRouter._compress_dict` was applied to `read_file` contents that parse as JSON, adding a fabricated `"status": "unknown"` field (and renaming long `content` / truncating `error` keys) in what the model saw; such reads could also never count as full reads. Now `compress_tool_output`: file contents are only length-truncated (existing 200-char preview behavior and its test preserved), never parsed and rewritten. Test: `test_compact_mode_never_rewrites_file_contents`.
- Tests: `tests/test_structured_edit_wiring.py` (14, through the loop: replace after read, unread keyword replace refused with contents, prose contamination rejected, port patch preserves fields and format, JSON text replace refused, overwrite refused, root patch and type change refused, create-new allowed, wrong-path edit refused, off without calibration). Mutation: disabling language validation fails the prose test; disabling the overwrite/JSON policy fails 2 tests.
- Acceptance-test reformulations: "read/count tasks cannot write their answer" contradicts tasks that ask for the answer in a file → measured as `unread_source_writes` (mutations before a successful read of `source_paths`). "Write followed by an incorrect final claim must fail verification" → measured as `false_done` in the eval; a runtime task-level done gate is NOT built (needs a design decision — the runtime has no machine-checkable spec of the request). Added eval metric `damaged_files` (seeded file changed and lost JSON keys / Python top-level names / original text lines).

Four conditions, frozen corpus, guard ON, t=0, one run each, all on the same code (after the compression fix):

| | ungrounded/current | grounded/current | ungrounded/structured | grounded/structured |
|---|---|---|---|---|
| task success | 3/10 | 4/10 | 2/10 | 3/10 |
| first-attempt path | 4/9 | 8/9 | 4/9 | 6/9 |
| false done | 1 | 4 | 1 | 2 |
| damaged seeded files | 1 | 4 | 1 | 1 |
| unread-source writes | 1 | 1 | 0 | 1 |
| escalations | 6 | 1 | 8 | 6 |
| rounds / tool calls | 31 / 19 | 45 / 22 | 30 / 18 | 34 / 20 |
| prompt tokens | 18,629 | 28,976 | 25,415 | 27,763 |
| stray files / valid actions | 0 / 100% | 0 / 100% | 0 / 100% | 0 / 100% |

Readings (n=10, single run each: one-task differences are within noise):
- Structured editing collapses the grounded safety regression: damaged files 4 → 1, false done 4 → 2. It does not raise success; `fix_bug` fails in both structured conditions and escalations rise.
- Grounding gate (grounded/structured vs ungrounded/structured): damaged 1 = 1, **false done 2 vs 1 (regression)**, success 3 vs 2, first path 6/9 vs 4/9 → gate **not met**; grounding stays held.
- Traces: gemma never used `patch_json` (it repeats text `replace` on JSON after the refusal names patch_json, then escalates — no damage). In `fix_bug` it was shown `return a - b` and still issued `"add"`→`"subtract"` (renames the function; compiles; false done). Remaining errors are semantic misreadings the deterministic layer cannot detect without a task spec.
- Suite: 700 passed / 2 environmental / 8 skipped.

**Decisions (2026-09-13):** build B + C, not A (model-declared checks are circular trust). Grounding off. Structured editing off by default; re-evaluate inside the bounded lane.

## B — completion invariant: named existing files must be read (2026-09-13)
- `core/path_candidates.named_existing_files`: requirements from the request — a reference that exists as written, or a bare file name with exact-name matches (any one satisfies an ambiguous name). New files, near-names and escapes create none.
- Loop (calibration `require_read_named_files`, **enabled in the `"1b"` preset**): computed at run start; a finish (compact `done` or plain text) with an unmet requirement is not returned — a `[completion check]` user message names the files, `done.rejected` is emitted; the second unmet finish raises `EscalationRequired(reason="completion_prerequisites_unmet")`. A successful `read_file` satisfies (full read not required, else files over the 200-char compact preview could never complete); a file the agent deleted satisfies. Tests: `tests/test_completion_gate.py` (6).
- Measured (frozen corpus, preset, lane off, vs clean ungrounded/current baseline): identical task outcomes (3/10, same tasks, false done 1 → 1); rounds 31 → 35. Trace (`edit_config`): gemma overwrote config.json with `8080`, the gate then forced a read of the already-destroyed file, which satisfied it. **Finding:** "read before done" does not force looking before acting; the stronger invariant would be "a named existing file must be read before its first mutation" (not implemented — policy change pending).

## C — bounded task lane (2026-09-13)
- `core/bounded_task.py` (complete): `TaskSpec(instruction, mutable_paths, checks, allow_code_execution, accept_unverified_proposal)`; checks are declarative — postcondition (`file_equals`, `file_contains`, `json_pointer_equals` [type-exact], `file_absent`, `python_call_equals` [subprocess, isolated cwd, `-I`, timeout; requires `allow_code_execution`]) and sanity (`python_compiles`, `json_keys_preserved`), plus an always-on scope check (nothing outside `mutable_paths` changed, via before/after sha256 snapshot). `eligibility_problems`: bounded exact paths, known check types, checks target mutable paths, code checks explicitly allowed, ≥1 postcondition unless `accept_unverified_proposal`. `run_bounded_task` → `verified_done` (all checks incl. a postcondition pass — also when the agent escalated afterwards; the checks are authoritative in both directions), `proposal_complete` (only opted-in sanity-only specs), `escalate` (ineligible — model never called; any failed check; agent escalation/error with an unproven outcome). The model's own completion claim never decides the state.
- Tests: `tests/test_bounded_task.py` (11) incl. the traced false completion (rename to `subtract` + "Task completed successfully." → escalate), config wipe (lost keys), string-typed port, out-of-scope stray file, isolated code check timeout, ineligible semantic task never calls the model, proven outcome after agent escalation.
- Not built: natural-language → TaskSpec translation (coordinator responsibility); the CLI free-text path is unchanged and does not use the lane.
- Eval: `--lane` runs each frozen task through `run_bounded_task` with the declarative `LANE_SPECS` (independent of the eval's `task.check`); reports `lane_states`, `lane_false_verified`, `lane_missed_success`. Test: every corpus task has an eligible spec touching only seeded/expected paths.

| frozen corpus, t=0, 1 run each, grounding off | baseline (B off) | B, no lane | lane + current edits | lane + structured edits |
|---|---|---|---|---|
| task success (eval check) | 3/10 | 3/10 | 3/10 | 2/10 |
| model false "done" claims | 1 | 1 | 1 | 0 |
| **authoritative false done** | 1 | 1 | **0** | **0** |
| lane verified_done / escalate | – | – | 3 / 7 | 2 / 8 |
| lane false verified / missed success | – | – | **0 / 0** | **0 / 0** |
| damaged seeded files | 1 | 1 | 1 | 1 |
| rounds / tool calls | 31 / 19 | 35 / 21 | 35 / 21 | 36 / 19 |
| prompt tokens | 18,629 | 21,849 | 21,849 | 33,670 |

- The lane's verified_done agreed with the independent eval check on all 20 lane task runs. The one false completion (config wipe) became `escalate: verification failed: json_pointer_equals (/port=(missing)); json_keys_preserved (lost keys ['/name'])`. Damage still happens inside mutable paths (the lane reports it; it does not roll back).
- Found and fixed during evaluation: the first runner let an agent escalation override passing checks (`hello_script` was created correctly, then the agent tripped repeat detection) — contradicting the verified_done definition.
- Structured editing inside the lane: one fewer verified success (fix_bug semantic rename) and ~54% more prompt tokens (33,670 vs 21,849; ~16.8k vs ~7.3k per verified success) — no evidence yet to enable it.
- Suite: 719 passed / 2 environmental / 8 skipped.

## Slice 1 — realistic repo corpus, exact-path B, controlled Gemma/Qwen baselines (2026-09-13)
Plan: `C:\Users\thewi\.claude\plans\worked-for-43s-i-proud-hamming.md` (approved with 7 amendments).

Built:
- **B, exact path** (`AgentLoop._enforce_named_read_before_mutation`, key `require_read_named_files`, on in `"1b"`): write/replace/patch of a file named by the request requires that exact path in the successful `read_file` set; another candidate or guard-shown contents do not count; delete exempt; reason `named_file_unread`. Tests: wipe replay, ambiguity (`src/config.json` read does not unlock `config/config.json`), delete exempt, unnamed unaffected, off without calibration. Mutation: disabling it fails exactly the wipe and ambiguity tests.
- **Production checks** (`core/bounded_task.py`): `python_expr_equals` (postcondition; runs code in a temp copy with the copy on `PYTHONPATH`) and `pytest_passes` (sanity/regression; public tests only; unique `--basetemp` per invocation). Both require `allow_code_execution`; neither leaves artifacts in the workspace. Deviations from the plan text: `pytest_passes` is a sanity check, not the postcondition (public postconditions are expression checks, so repos contain no failing tests that reveal expected behavior); `python_expr_equals` added because `python_call_equals` cannot import package modules.
- **Text tool protocol** (`OllamaModel(text_tool_protocol=True)`, calibration `text_tool_protocol`): forces the text JSON action interface for tool-capable models so model comparisons hold the interface constant.
- **Corpus**: `benchmark/repos/{mathlib,configsvc,textkit,inventory}` (packages, cross-module imports, passing `tests/test_core.py`, same-name distractors `legacy/operations.py`, `legacy/app.json`, `tools/slugify.py`, `backup/items.json`); `benchmark/oracle/<repo>/hidden/test_<task>.py` (32 hidden tests, outside repo trees); `benchmark/repo_tasks.py` (40 tasks: 20 dev / 20 heldout, 32 solvable / 8 insufficient-evidence; `RepoTask(public_spec, oracle: OracleSpec(hidden_test_ids), gold_files, gold_symbols, reference_patch, missing_fact, expected_outcome)`). Root `conftest.py` excludes repos/oracle from project collection.
- **Evaluator** `benchmark/repo_task_eval.py`: own oracle (copies final workspace, adds id-resolved hidden tests, separate pytest subprocess — never `run_check`); `lane_false_verified`, `false_completion_on_insufficient_evidence`, `model_false_done_claim`; localization `read_recall`, `read_precision`, `mutation_precision`, `gold_first_touch`, `first_gold_rank`, `gold_edit_recall`; leakage recorder over every message sent to the model; fingerprint = task + corpus hash + harness source hash + condition + exact model digest + overrides + max rounds + public spec; rows appended with flush + fsync; stale fingerprints ignored; model unloaded with `keep_alive: 0` and `/api/ps` polled between conditions (verified on Ollama 0.34). One shared `HARNESS_POLICY`; conditions differ only in model (`gemma_constrained` vs `qwen_constrained`) or interface (`qwen_constrained` vs `qwen_native`).
- Tests: `tests/test_repo_corpus.py` (structure; missing facts absent from repos — mechanical literal check, not a proof of unsolvability; leakage boundary; every solvable task: postconditions and oracle fail untouched, reference patch → lane `verified_done` and oracle passes). Mutation: oracle-always-pass, checks-always-pass and no-op reference patch are all detected. `tests/test_repo_task_eval.py` (conditions differ only in the named factor; **oracle catches a verifier forced to always pass** — lane verified_done + oracle fail; localization precision penalizes shotgun reading; leakage markers; fingerprint sensitivity; fsync + partial-line recovery; stale rows ignored).
- Suite: 740 passed / 2 environmental / 8 skipped (~100 s; corpus self-validation ≈ 60 s).

Dev-split baselines (20 tasks each, temperature 0, identical harness policy; corpus `e4c8be9234e7`, harness `4d087328c832`; no OOM restarts):

**Primary comparison — model identity (same text protocol + constraint):**
| | gemma_constrained | qwen_constrained |
|---|---|---|
| verified_done (solvable) | 0/16 | 0/16 |
| hidden oracle passed | 0/16 | 0/16 |
| false completion on insufficient evidence | 0/4 | 0/4 |
| model false "done" claims | 6 | 9 |
| read recall / precision | 0.146 / 1.0 | 0.125 / 0.5 |
| mutation precision / gold edit recall | 0.4 / 0.083 | 0.143 / 0.062 |
| gold first touch | 3/16 | 2/16 |
| tasks with damaged / stray files | 2 / 5 | 3 / 5 |
| agent escalations | 13 | 9 |
| rounds / prompt tokens | 67 / 48,635 | 86 / 71,388 |

**Secondary comparison — action interface (Qwen):**
| | qwen_constrained | qwen_native |
|---|---|---|
| verified_done (solvable) | 0/16 | 0/16 |
| model false "done" claims | 9 | 12 |
| read recall / precision | 0.125 / 0.5 | 0.208 / 0.667 |
| gold first touch | 2/16 | 4/16 |
| rounds / prompt tokens | 86 / 71,388 | 66 / 55,619 |

Probe (`mathlib_median_even`): constrained requests carry `format` and no `tools`; native requests carry `tools` and no `format` — the conditions are wired differently, but qwen2.5-coder:1.5b answers native tool offers with text JSON, so both interfaces often yield identical actions at temperature 0. Dominant failures in all conditions: invented paths with no near match (`data.csv`, `median.py`, `subtract.js`), stray new files, edits to distractors (`legacy/app.json`), broken rewrites. Leaks: 0 in 60 runs. The irrelevant ArrayHelper hint still appears and was echoed as a final answer.

Decision table (dev split only; heldout not run):
| Evidence | Result | Decision |
|---|---|---|
| Qwen constrained > Gemma constrained on task success | 0/16 = 0/16 (floor) | **not shown** |
| Qwen localization precision materially higher | lower (0.5 vs 1.0, few reads) | **no evidence for Qwen cartographer** |
| Qwen native > Qwen constrained | 0/16 = 0/16; more false done claims | **not shown** |
| hidden-oracle false-verified = 0 | 0, but vacuous on these runs (no verified_done occurred); the positive path is covered by corpus self-validation (32/32 reference patches verified and oracle-passed) | lane remains trustworthy as far as tested |
| high false done, low hidden pass | 6–12 false claims, 0 hidden passes | **model self-evaluation stays untrusted** |
| low localization, low success | recall 0.13–0.21, success 0 | **build deterministic localization tools next** |
| Qwen not materially better | yes | **do not assign Qwen architect/integrator roles** |

Caveat: both models are at the floor on this corpus, so the model comparison cannot discriminate; "not materially better" is shown, "not worse" is not. The corpus is harder than the 1–1.5B models' current capability in this harness.

## Slice 2 — deterministic repository intelligence + tool adoption (in progress, 2026-09-14)
Machine prep: removed session temp artifacts, uv cache, duplicate Gemma model, loose `gemma-3-1b-it-Q4_K_M.gguf`, stale `cordelite-agent`; disk free 20.3 → 21.97 GB (filesystem change; uv reported 3.6 GiB deleted, less recovered because uv hardlinks into venvs). User env `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`; Ollama restarted; loading qwen evicted gemma (consistent with the policy; memory pressure could also force it).

Done so far:
- **Array hint removed from measured harness**: calibration `array_guidance` (default True keeps existing behavior/tests); False in `"1b"` preset and `HARNESS_POLICY`; gates both `[array context]` injection sites. Test: on → hint reaches the model's second call; off → never.
- **Residency evidence**: `repo_task_eval` (and probes) append `before` / `after_run` / `after_unload` snapshots — Ollama `/api/ps` models with size, available/total RAM via `GlobalMemoryStatusEx`, evaluator-process env — to `*_residency.jsonl` (fsync). The env fields reflect the evaluator process, not the Ollama server (server policy verified behaviorally).
- **`core/repo_index.py`** (complete): stdlib-AST index — files, modules, symbols (function/class/method/constant with line spans), resolved internal imports incl. relative, `__all__`/package re-exports, references (Name/Attribute), calls per function, test-file heuristics; mtime/size-keyed cache; every output capped at 4000 chars. Tools: `repo_outline`, `find_symbol` (DEFINED/EXPORTED/IMPORTED/REFERENCED; an invented file name like `median.py` is redirected to where `median` is defined), `find_references` (with enclosing function + line text), `find_tests` (by symbol or file, via package re-exports), `dependency_cone` (file imports/importers or symbol callers/callees, depth 1–3). Tests: `tests/test_repo_index.py` (10).
- **Exposure** (calibration `repo_tools`, NOT in any preset): FileTools schemas/handlers, `SchemaRouter.REPO_TOOLS` logical tools + anyOf branches + expansions, `REPO_TOOLS_GUIDANCE` appended to the compact prompt; repo tool outputs exempt from compact 200-char truncation (already bounded). Tests: `tests/test_repo_tools_wiring.py` (6). Mutation: removing the truncation exemption fails the loop test (an earlier `len > 200` assertion missed it — truncated output is 203 chars — and was replaced by exact equality).
- **`benchmark/protocol_probe_eval.py`**: 15 unambiguous one-action probes on `mathlib`; scores `semantic_choice_correct`, `protocol_encoding` (native tool_calls field / text_json / invalid, from the raw Ollama message), `executed` (via `AgentLoop._execute_tool_call`); fingerprinted rows (probe, condition, digest, harness, repo hash, system prompt, probe source), residency snapshots, unload between conditions. Tests: `tests/test_protocol_probe_eval.py` (5; system prompt equals what the loop sends).

Protocol probe results (temperature 0, `repo_tools` on, same policy):
| | gemma_constrained | qwen_constrained | qwen_native |
|---|---|---|---|
| run 1 (concrete prompt examples) correct choice | 8/15 | 14/15 | 14/15 |
| run 2 (placeholder examples) correct choice | **9/15** | **14/15** | **14/15** |
| protocol encoding (run 2) | 15 text_json | 15 text_json | 15 text_json |
| executed (run 2) | 14/15 | 15/15 | 15/15 |
| args copied from prompt examples | run 1: 6 of 7 Gemma errors, Qwen's 1 error; run 2: 0 | | |

- Run 1 exposed a prompt artifact: models copied the example values `parse_date` / `app/dates.py` / `app/` into arguments. Run 2 replaced them with `<...>` placeholders (one iteration on a protocol-dev instrument; not the headline benchmark).
- Remaining Gemma errors: `find_references` chosen for tests/dependency questions, `repo_outline` for a where-defined question, `test_core.py` without `tests/`. Qwen: reads `calculator.py` instead of `dependency_cone` for the paraphrased cone probe.
- qwen2.5-coder:1.5b never uses Ollama's native `tool_calls` field even when offered tools (15/15 text JSON in the native condition).
- Residency: no model loaded before any condition; unload confirmed after each; available RAM during runs 169–306 MB (qwen occupies 2.0 GB vs gemma 0.9 GB).
- Suite: 764 passed / 2 environmental / 8 skipped (after the placeholder prompt change).

Remaining in Slice 2: localization-only benchmark; L0/L1/L2 calibration tier; end-to-end reruns (baseline vs + repo intelligence) for Gemma and Qwen.

### Localization-only benchmark — pre-registered before any run (2026-09-14)
Instrument: `benchmark/localization_eval.py` (tests: `tests/test_localization_eval.py`). Calibration `navigation_only` removes mutating actions from the constrained schema and the loop refuses any that arrive (`navigation_only` rejection); workspace snapshot compared before/after. Instruction wrapper `LOCALIZE_TEMPLATE` asks for `FILES: ...; SYMBOLS: ...` in the done summary. Tasks: the 16 solvable dev tasks. Conditions: `gemma_baseline`, `gemma_repo_tools`, `qwen_baseline`, `qwen_repo_tools` (constrained, temperature 0, identical policy; only model or `repo_tools` differs). qwen_native omitted: probes showed identical behavior to qwen_constrained and it doubles 2 GB model loads.

Reported metrics (protocol failure kept separate from localization):
- declared gold-file recall and precision; declared gold-symbol recall and precision (tasks with gold symbols only)
- touched-file recall/precision (files the agent actually read/targeted)
- tasks touching gold and mean first-gold rank over touched files
- invented-path rate = path-bearing calls to non-existent paths / path-bearing calls
- protocol-failure rate = (schema-invalid replies + navigation_only refusals) / model replies
- write attempts and workspace-changed tasks (acceptance requires workspace changes = 0)

Interpretation rules fixed in advance:
- repo_tools "improves localization" only if declared file recall AND precision both rise for that model, with invented-path rate not rising.
- If both models stay low with tools available and protocol failures are high → bottleneck is protocol/tool selection, not repository structure.
- If localization rises sharply with tools → repository structure was a missing capability; carry repo_tools into the L0/L1/L2 and end-to-end reruns.
- No prompt or instruction change after seeing condition-specific results unless all four conditions are rerun under the revised text.
- Single run per condition at temperature 0 on 16 tasks: differences of 1–2 tasks are within noise.

### Localization-only results (2026-09-14; no prompt/instruction changes between conditions)
| 16 solvable dev tasks | gemma_baseline | gemma_repo_tools | qwen_baseline | qwen_repo_tools |
|---|---|---|---|---|
| declarations made | 4/16 | 5/16 | 13/16 | 13/16 |
| declared file recall / precision | 0.146 / 0.625 | 0.083 / 0.500 | 0.250 / 0.212 | 0.312 / 0.253 |
| declared symbol recall / precision | 0.0 / 0.0 | 0.0 / 0.0 | 0.75 / 1.0 | 0.75 / 0.81 |
| touched file recall / precision | 0.083 / 0.5 | 0.083 / 0.5 | 0.25 / 0.6 | 0.188 / 0.6 |
| tasks touching a gold file | 2/16 | 2/16 | 4/16 | 3/16 |
| invented-path rate (path-bearing calls) | 14/18 | 16/21 | 0/7 | 3/8 |
| protocol-failure rate (replies) | 2/48 | 0/52 | 0/41 | 0/46 |
| tasks with 0 tool calls | 0 | 0 | 11 | 9 |
| tasks using any repo tool | – | 5 | – | 5 |
| escalations | 12 | 10 | 2 | 2 |
| write attempts / workspace changed | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| prompt tokens | 24,433 | 38,116 | 30,794 | 42,936 |

Residency: no model loaded before any condition; unload confirmed after each; minimum available RAM 259 MB (qwen_baseline after_run).

Against the pre-registered rules:
- Gemma: file recall and precision both fell (0.146→0.083, 0.625→0.500) → **no improvement**.
- Qwen: file recall and precision both rose (0.250→0.312, 0.212→0.253) but the invented-path rate rose (0/7→3/8) → **rule not met**; the recall gain is ≈1 task (within noise). Symbol precision fell 1.0→0.81.
- Protocol failures stayed low (0–4%), so the "protocol failure" branch does not apply either.

Failure mode the rules did not anticipate — **tool non-adoption, not encoding**:
- Qwen answered without exploring on 11/16 (baseline) and 9/16 (tools) tasks, declaring files from priors (`subtract.js`, `index.js`, `median.py`, `total_value.py`); when it did use repo tools on the inventory tasks it over-declared the whole package (low precision).
- Gemma always acts but mostly by reading invented paths (14–16 of 18–21 path calls), escalating on repeat; it used repo tools on only 5/16 tasks.
- Qwen's symbol recall is 0.75 in both conditions: it names the right function from the task text while pointing at the wrong or invented file — understanding "what" without locating "where".

### L0 / L1 / L2 localization experiment — pre-registered before any run (2026-09-14)
Built (behind calibration, in no preset):
- `core/grounding.targeted_grounding` — per request: existing path grounding lines, `X.py: no such file; X: defined in ...` redirects, and `- name: defined in file line N; exported by ...` for identifiers naming real symbols (max 6). No repo outline. Returns evidence = existing paths it established. Dry run over the 16 dev tasks: ≤ 2 facts per task, no spurious symbol matches from the instruction wrapper.
- `core/path_candidates.declared_paths` — shared path extraction (known file extensions only; `calculator.evaluate` is not a file).
- Loop `targeted_grounding` (L1): facts injected as a system message before the first model call; `request.grounded` event with lines and evidence.
- Loop `evidence_gated_completion` (L2): a finish that names a path not existing or not in the run's evidence (grounding, successful `read_file`, paths in `search_files`/repo-tool output) is rejected with `[completion check] No evidence for: ...`; the second rejection escalates `unsupported_declaration`. Tests: `tests/test_evidence_gate.py` (9). Mutation: disabling evidence recording fails 3 tests; disabling the gate fails 4.
- Evaluator adds `unsupported_declaration_rate` computed from events independently of the loop (`observed_evidence`), plus evidence-gate rejections and escalation reasons.

Conditions (constrained, temperature 0, `navigation_only`, `repo_tools` available in all levels; only the level flags or the model differ): `{gemma,qwen}_L0` (no grounding, no gate), `_L1` (grounding), `_L2` (grounding + gate). L0 equals the previous `*_repo_tools` condition but is rerun on the current code.

Criteria fixed in advance (in addition to the earlier localization metrics):
- L1 improves localization for a model only if declared file recall AND precision both rise vs L0 and the invented-path rate does not rise.
- L2's unsupported-declaration rate should be ~0 for accepted answers by construction; L2 counts as improving useful behavior only if declared file recall and precision are ≥ L1. A drop in declarations made or a rise in `unsupported_declaration` escalations is reported as the suppression cost, not as success.
- Differences of 1–2 tasks out of 16 are within noise. No instruction, prompt or grounding-text changes during the experiment.

Results (dev, 16 tasks, sequential, model unloaded between conditions; 0 writes, 0 workspace changes in all six):

| metric | gemma L0 | gemma L1 | gemma L2 | qwen L0 | qwen L1 | qwen L2 |
|---|---|---|---|---|---|---|
| declarations | 5 | 11 | 10 | 13 | 14 | 14 |
| file recall | 0.083 | 0.583 | 0.521 | 0.312 | 0.688 | 0.688 |
| file precision | 0.500 | 0.818 | 0.850 | 0.253 | 0.750 | 0.750 |
| symbol recall / precision | 0 / 0 | 0.25 / 0.17 | 0.17 / 0.21 | 0.75 / 0.81 | 0.83 / 0.95 | 0.83 / 0.95 |
| invented path calls | 16/21 | 5/13 | 5/13 | 3/8 | 1/7 | 1/7 |
| unsupported declarations | 1/4 | 0/13 | 0/11 | 12/25 | 0/15 | 0/15 |
| gate rejections | 0 | 0 | 9 | 0 | 0 | 2 |
| escalations | 10 | 5 | 6 | 2 | 1 | 2 |
| protocol failures | 0/52 | 3/53 | 5/52 | 0/46 | 0/43 | 0/34 |
| tool calls | 24 | 16 | 16 | 12 | 9 | 9 |

Verdict against the criteria:
- L1: passes for both models. Recall and precision both rose well beyond noise (gemma 0.08→0.58, qwen 0.31→0.69), and invented-path rates fell. Unsupported declarations dropped to 0 without any gate. Gemma protocol failures rose 0→3 (small; recorded).
- L2: does not meet "≥ L1". Qwen L2 = L1 exactly. Gemma recall 0.583→0.521 (one task, `inventory_total_value`, which escalated `truncated_output` with no gate rejection, so it is noise unrelated to the gate). The gate fired only on tasks where L1 declared no files anyway (gemma: 4 config/inventory tasks + divide_zero; qwen: divide_zero), converting them into `unsupported_declaration` escalations. Suppression cost is ~0, but so is the benefit: grounding already removed unsupported declarations on this corpus. L2 stays a safety invariant, not a capability claim.
- Gap: rejected paths are in `done.rejected` events but not persisted to result rows, so what gemma declared in those 9 rejections is NOT VERIFIED.
- Residency: only the tested model loaded after each run; available RAM after unload 847–1436 MB; no OOM.
- Decision: L1 proceeds to end-to-end evaluation. L2 stays implemented, default off, as a candidate safety control to re-test once localization recall is high.

### End-to-end L1 on the repo corpus (pre-registered before running)
Conditions: `{gemma,qwen}_constrained` (rerun, since the harness hash changed after Slice 1) vs `{gemma,qwen}_L1` = the same overrides + `targeted_grounding: True`. Evidence gate off, repo_tools off in both, so grounding is the single factor. Dev split, sequential, model unloaded between conditions.
Criteria, per model, L1 vs its constrained rerun:
- Primary: `oracle_passed_solvable` (the hidden oracle, independent of the lane). L1 counts as improving end-to-end success only if this rises by ≥ 3 tasks; 1–2 = noise.
- Must not regress: `lane_false_verified` stays 0; `false_completion_on_insufficient_evidence` does not rise; `damaged_file_tasks` does not rise.
- Secondary, reported, not decisive: read_recall/precision, gold_first_touch, mutation_precision, gold_edit_recall, escalations, prompt tokens.
- If localization metrics rise but oracle success doesn't, localization is not the end-to-end bottleneck. Diagnose L1 failures by cause before any further intervention.

### End-to-end L1 — raw results (frozen 2026-09-14, before interpretation)
Dev split, 20 tasks (16 solvable, 4 insufficient-evidence) per condition, sequential, unload confirmed after each. Summary frozen at `benchmark/results/e2e_l1_summary_frozen.json`; rows in `benchmark/results/repo_task_eval.jsonl`. Minimum available RAM 108 MB (qwen_L1 after_run); no OOM.

| | gemma_constrained | gemma_L1 | qwen_constrained | qwen_L1 |
|---|---|---|---|---|
| oracle_passed_solvable | 0/16 | 0/16 | 0/16 | 0/16 |
| verified_done_solvable | 0/16 | 0/16 | 0/16 | 0/16 |
| lane_false_verified | 0 | 0 | 0 | 0 |
| false completion, insufficient evidence | 0/4 | 0/4 | 0/4 | 0/4 |
| damaged_file_tasks | 0 | 2 | 4 | 6 |
| stray_file_tasks | 5 | 0 | 9 | 2 |
| model false done claims | 3 | 8 | 18 | 16 |
| read recall / precision | 0.0 / 0.0 | 0.562 / 0.9 | 0.333 / 0.714 | 0.521 / 0.818 |
| mutation precision | 0.0 | 1.0 | 0.231 | 0.5 |
| gold first touch | 0/16 | 9/16 | 5/16 | 9/16 |
| gold edit recall | 0.0 | 0.125 | 0.146 | 0.208 |
| agent escalations | 13 | 9 | 2 | 4 |
| invalid actions | 1 | 0 | 0 | 0 |
| rounds / prompt tokens | 93 / 86,321 | 87 / 73,889 | 87 / 53,445 | 75 / 49,549 |
| leaks | 0 | 0 | 0 | 0 |

### End-to-end L1 — gate verdict (as pre-registered, unmodified)
- Gemma: primary 0 → 0 (needs ≥ +3) **FAIL**. Must-not-regress: false verified 0 ✓, insufficient-evidence false completions 0 → 0 ✓, damaged-file tasks 0 → 2 **FAIL**.
- Qwen: primary 0 → 0 **FAIL**. False verified 0 ✓, insufficient 0 → 0 ✓, damaged-file tasks 4 → 6 **FAIL**.
- **L1 gate: FAILED for both models.**

### End-to-end L1 — analysis (separate from the verdict)
- Pre-registered branch that applies: localization rose (read recall 0 → 0.56 Gemma, 0.33 → 0.52 Qwen; gold first touch 0 → 9 and 5 → 9) while oracle success stayed 0, so **localization is not the end-to-end bottleneck on this corpus.**
- Damage context: Gemma's 2 damaged tasks (`textkit/cli.py`, `textkit/formatting.py`) are edits to the correct file that broke it. Baseline Gemma never mutated a gold file, so it could not damage one. Stray-file tasks fell (5 → 0, 9 → 2). This explains the regression; it does not waive it.
- The first real lane audit happened here: the lane escalated every task and the oracle agreed on all 80 runs. False verified is still 0 but not a positive-path test, since no run verified.
- Grounding surfaced every gold file for 15/16 solvable tasks. `mathlib_add_power` got 1 of 3: `__init__.py` and `calculator.py` aren't named in the prompt.

Failure classification, L1 conditions, one primary cause per solvable task, using the six pre-agreed causes (no seventh needed). Evidence: rows `files_read`, `files_mutated`, `guard_rejections`, lane reason, plus deterministic `targeted_grounding` recomputed per task.

| cause | gemma_L1 | qwen_L1 |
|---|---|---|
| 1 gold file never proposed | 1 (`add_power`: 2/3 gold files not grounded, nothing read) | 0 |
| 2 correct file available but ignored | 1 (`find_missing`) | 5 (`find_missing`, `low_stock_equal`, `median_even`, `divide_zero` [wrote app.js/index.html/server.js], `file_overrides_defaults` [edited config/app.json instead of grounded settings.py]) |
| 3 ambiguous grounding (gold + same-name distractor offered, wrong/nonexistent choice) | 5 (`service_port`, `database_host`, `add_feature`, `update_qty`: wrong_path refusals; `fix_subtract`: read legacy/operations.py) | 2 (`update_qty`: edited backup/items.json; `fix_subtract`: edited legacy/operations.py) |
| 4 symbol-level miss inside the correct file | not separable from 6 with persisted data | same |
| 5 premature narrowing to one file | 0 | 1 (`add_power`: edited operations.py only) |
| 6 correct evidence read, wrong or no conclusion | 9 (7 read gold and never edited; `cli_upper`, `truncate_limit` edited gold and damaged it) | 8 (`slug_spaces`, `slug_punctuation`, `cli_upper`, `total_value`, `add_feature` no edit; `database_host`, `service_port` wiped JSON keys; `truncate_limit` wrong edit) |

Limits of this classification (NOT VERIFIED):
- `guard_rejections` rows carry the reason but not the attempted path. For Gemma's wrong_path cases, the path is inferred from the guard rule: a missing target whose file name exists elsewhere.
- Cause 4 vs 6 needs per-call arguments and model replies, which aren't persisted. Tasks are counted under 6.

Reading: cause 6 dominates (9/16, 8/16). Semantic interpretation and edit quality is the isolated next bottleneck. Cause 3 is the main remaining localization loss for Gemma (5/16) and involves the corpus's deliberate same-name distractors.


> Superseded (2026-09-14): the note below was written after the localization-only run. Candidate (a) became L1 `targeted_grounding` (targeted facts, not the outline); (b) became L2 `evidence_gated_completion`.

Implication for the next policy decision (not implemented): exposing the index as optional tools does not change behavior; the models do not choose to consult it. Candidate deterministic responses to evaluate next: (a) inject `repo_outline` (or `find_symbol` for names in the request) into context before the first call instead of offering it as a tool; (b) a declaration gate — declared files must exist and must have been touched (read or tool target) before `done` is accepted, generalizing the completion invariant.
- Eval sets are small (30 / 5); numbers are directional, not a benchmark score.

## Milestone: v2.0-baseline-stable (2026-08-30)
- **Model:** `qwen2.5-coder:1.5b`
- **Deterministic suite:** 288 passed, 8 skipped
- **Live integration:** 4/4 passed in ~9.47s
- **Validated invariants:**
  - 1.5B baseline stable
  - 33k context hygiene (pruner token+message pass, tool-result truncation)
  - Zero-token `lite` profile
  - Calibration centralization + validation (`validate_calibration` wired into `resolve_calibration`)
  - Profile isolation (`lite` excludes `semantic_router`/`embedding_model`)
  - Injection hardening (`[injected context]` prefix, `user` role)
  - Event hygiene (exactly one `turn.start`/`turn.end`, one `turn.round` per iteration)


### Instrumentation + provenance (2026-09-14, after the L1 verdict; no model runs)
- `benchmark/repo_task_eval.py` rows now also carry:
  - `calls`: round, tool, args (strings > 300 chars summarized as chars/sha256/head), success, result head.
  - `read_views`: per successful read, `file_chars`, `shown_chars`, and `complete` = the text the model received equals the seeded file; None after an earlier mutation of that file.
  - `write_diffs`: capped unified diff per changed seeded file, plus created and deleted files.
  - `model_outputs`: raw replies, capped at 1500 chars.
  - Full `guard_rejections`: tool, path, candidates, round, outcome.
  - `experiment`: condition, model and digest, corpus/harness/overrides sha256, max rounds, python version, run start time, and the gate path + sha256 (`--gate`). The gate is deliberately NOT part of the run fingerprint.
- `benchmark/gates/e2e_l1_v1.md`: the L1 gate text, filed after evaluation (noted in the file).
- Tests: `tests/test_repo_task_eval.py`, 4 new. One goes through the real `run_task` path with only the model's chat scripted. Mutations "reads always complete", "no diffs" and "ignore mutation history" each fail 2 tests.
- Editing the evaluator changed the harness hash, so the frozen L1 rows no longer match current fingerprints. Their record is `benchmark/results/e2e_l1_summary_frozen.json` plus the rows themselves.
- `scripts/baseline_gate.ps1` repaired:
  - Uses the venv python and a TEMP basetemp (was bare `pytest` and `C:\tmp`).
  - `MIN_PASSED` 288 → 785.
  - Explicit allowlist of the 2 known environmental failures; any other FAILED id fails the gate. Previously the known failures made it always throw.
  - Verified: `-SkipLive` → `baseline=OK passed=785 skipped=8`. With a temporary failing test added → "pytest reported unexpected failures", exit non-zero; probe removed. Live gate NOT VERIFIED.

### Finding: compact reads show at most 200 characters (confound for cause 6)
- `SchemaRouter.compress_tool_output` truncates `read_file` results to `_PREVIEW_LIMIT = 200` characters in compact mode (`plugins/agent/schema_router.py:177`, `:412-413`). The named-file invariant accepts such a partial read.
- Dev gold files over 200 chars: `inventory/service.py` (277; the cut falls inside `def find_` so `find_item` is never shown), `configsvc/settings.py` (276; the cut falls inside the bug line `{**data, **D|EFAULTS}`), `calculator.py` (218).
- So "read the gold file" does not imply "saw the defect" for `inventory_find_missing`, `config_file_overrides_defaults`, and the `calculator.py` part of `mathlib_add_power`. Gemma's `config_file_overrides_defaults` was classified as cause 6 but the model was never shown the buggy expression. Real-world files are far larger than this corpus, so the limit would dominate there.
- Not changed. Changing it is an intervention and needs its own pre-registration.
- Provenance of the finding: first recorded 2026-09-13 in "Proficiency phase 2 — step 1" ("shows the model only the first 200 chars of any read ... relevant to step 4") but never carried into Open Items or any gate. Re-found here by measuring gold file sizes against the preview limit.

### diagnose_v1 — pre-registration + build (2026-09-14; not yet run)
- Gate text: `benchmark/gates/diagnose_v1.md` (sha256 `004b9f96dbc8…`), written before any code for the mechanism. Complete read views are held fixed in both arms; the only factor is diagnosis before mutation.
- Harness, all behind calibration, in no preset:
  - `full_read_views`: `SchemaRouter.compress_tool_output` returns reads whole.
  - `diagnose_before_mutation`:
    - `diagnose` logical tool and `FileTools.diagnose`: evidence must occur in the current file per `core/diagnosis.evidence_line_span` (whitespace-collapsed, ≥ 5 non-space chars).
    - `AgentLoop._enforce_diagnosis`: an existing file may be mutated only after a successful diagnose on that exact path; reason `diagnosis_required`.
    - `DIAGNOSE_GUIDANCE` appended to the compact prompt.
- Evaluator:
  - Conditions `{gemma,qwen}_fullread` / `_diagnose`.
  - Row fields `truncated_read_views`, `gold_shown_complete`, `diagnoses` (evaluator-side defect hit from the reference patch via `defect_lines`), `invalid_gold_files`, `failure_split`.
  - Summary `diagnose_gate_metrics`: invalid rows excluded, `oracle_passed_valid_solvable`, coverage, diagnosis and defect-hit rates, split counts.
  - `HARNESS_SOURCES` now also hashes `core/grounding.py`, `core/repo_index.py` and `core/diagnosis.py`. Grounding and the index were previously missing from the fingerprint.
- Tests:
  - `tests/test_diagnose_gate.py` (5).
  - `tests/test_repo_task_eval.py` +5, including a scripted end-to-end diagnose run through the real `run_task`: correct fix → lane `verified_done` + oracle pass; wrong fix → `wrong_edit_choice`; L1 read → `no_gold_view` with a truncated view.
  - Mutations: no guard (3 fail), full reads ignored (2), always-hit (1), truncated rows counted (1).
- Suite: 795 passed / 2 environmental / 8 skipped; `baseline_gate.ps1` `MIN_PASSED` → 795.
- Live wiring smoke (1 task, `gemma_diagnose`, `mathlib_fix_subtract`, scratch results file, EXCLUDED from the gate): row fields and gate hash populated, model unloaded. Gemma proposed `operations.py` (wrong_path) and escalated before any diagnose. No text was changed after seeing it.

### diagnose_v1 — raw results (frozen 2026-09-14, before interpretation)
Dev split, 20 tasks per condition (16 solvable). Summary frozen at `benchmark/results/diagnose_v1_summary_frozen.json`. Every row carries gate sha256 `004b9f96dbc8…`; 0 duplicate rows.
Execution: two background attempts were killed for low system memory (2, then 8 rows saved). The rest ran in foreground batches of 4, with the model unloaded after each batch, after leftover ChatGPT processes were ended (free RAM 1155 → 1592 MB). Resume is fingerprint-based, so killed in-flight runs were never written.

| | gemma_fullread | gemma_diagnose | qwen_fullread | qwen_diagnose |
|---|---|---|---|---|
| invalid solvable rows (truncated reads) | 0 | 0 | 0 | 0 |
| oracle_passed_valid_solvable | 0/16 | 0/16 | 0/16 | 1/16 |
| verified_done_solvable | 0/16 | 0/16 | 0/16 | 1/16 |
| lane_false_verified | 0 | 0 | 0 | 0 |
| false completion, insufficient evidence | 0/4 | 0/4 | 0/4 | 0/4 |
| damaged_file_tasks | 2 | 0 | 6 | 0 |
| stray_file_tasks | 0 | 0 | 3 | 2 |
| gold_shown_complete | 9/16 | 9/16 | 8/16 | 6/16 |
| tasks with successful diagnosis / defect hit | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 2 |
| diagnosis_required rejections | 0 | 10 | 0 | 29 |
| failure split | no_gold_view 7, gold_viewed_failed 9 | no_gold_view 7, no_diagnosis_hit 9 | no_gold_view 8, gold_viewed_failed 8 | no_gold_view 10, no_diagnosis_hit 5 |
| gold edit recall / mutation precision | 0.125 / 1.0 | 0.0 / – | 0.208 / 0.444 | 0.083 / 0.667 |
| model false done claims | 8 | 7 | 18 | 9 |
| escalations | 9 | 11 | 2 | 9 |
| rounds / prompt tokens | 87 / 74,067 | 78 / 74,816 | 76 / 50,183 | 98 / 99,106 |
| leaks | 0 | 0 | 0 | 0 |

### diagnose_v1 — gate verdict (as pre-registered, unmodified)
- Validity: 0 invalid rows in every arm → valid, not inconclusive.
- Gemma: primary 0 → 0 (needs ≥ +3) **FAIL**. False verified 0 ✓; insufficient-evidence 0 → 0 ✓; damaged 2 → 0 ✓.
- Qwen: primary 0 → 1 (+1, noise) **FAIL**. False verified 0 ✓; insufficient-evidence 0 → 0 ✓; damaged 6 → 0 ✓.
- **diagnose_v1: FAILED for both models.** Per the gate, no 2×2 follow-up.

### diagnose_v1 — analysis (separate from the verdict)
- **Gemma never used the mechanism.** 0 `diagnose` calls in 20 tasks. Only 2 tasks reached a refused mutation (10 rejections); 10 tasks ended in `repeated_failed_call` escalations before any edit. Damage fell 2 → 0 because edits stopped (gold edit recall 0.125 → 0), not because edits improved. The gate did not test diagnosis quality for Gemma: it measured non-adoption, the same failure as the optional repo tools.
- **Qwen tried and mostly failed the evidence check.** 21 `diagnose` calls, 2 accepted. 19 were refused because the quoted evidence was not text from the file (8 on `config/app.json`). 17/20 tasks hit a `diagnosis_required` refusal. Both accepted diagnoses hit the defect region:
  - `inventory_total_value` → edit → lane `verified_done` → oracle pass
  - `mathlib_add_power` → oracle fail
  Damage 6 → 0, but prompt tokens +97% and rounds +29%.
- The pre-registered failure split never reached `wrong_edit_choice` or `mechanical_failure` for either model. Failures stopped at "gold not shown completely" (7–10) or "no diagnosis hit" (5–9). So the bottleneck exposed here comes before the edit: models don't produce a verifiable, quoted diagnosis at all.
- Evidence coverage stayed about the same with full reads (gold_shown_complete 8–9/16 in the controls). About half the tasks fail before the model has seen every gold file, even with complete reads and grounding. Part of that is `mathlib_add_power` (3 gold files).
- **Lane-positive calibration milestone (first natural observation):** 1 natural `verified_done` (qwen_diagnose, `inventory_total_value`), and the oracle agreed. n = 1; recorded, not generalized.
- Descriptive only (different harness hash, not a pre-registered comparison): full reads alone did not change oracle success vs the L1 runs (0/16 both models).
- NOT VERIFIED: why Gemma never emitted `diagnose`. The model outputs are in the rows but have not been read yet.

### diagnose_v1 — forensic classification (2026-09-14; analysis only, no code or gate changes)
Sources: `model_outputs`, `calls`, `guard_rejections` and `diagnoses` in the diagnose-arm rows, plus seed files, task prompts and recomputed `targeted_grounding`. Every reply was read.

**Gemma (`gemma_diagnose`, 20 tasks) — one bucket per task**
| bucket | tasks | evidence |
|---|---|---|
| 1 understood diagnosis was required, chose another action | 0 | no reply references diagnosis |
| 2 prose diagnosis instead of the action | 0 | constrained decoding permits no prose; `done` summaries were "Task completed successfully." |
| 3 did not understand the action | 2: `mathlib_add_power`, `textkit_cli_upper` | 5 `diagnosis_required` refusals each, whose message names `diagnose`. Each answered with the same pattern 5×: re-read, then re-emit a byte-identical refused write. It never emitted `diagnose` (schema-valid emission was possible). The writes were themselves wrong (`export function` in Python, `slugify` in cli.py). |
| 4 never reached a point where diagnose was realistic | 10: `fix_subtract`, `service_port`, `database_host`, `add_feature`, `database_password`*, `slug_spaces`, `style_guide`*, `update_qty`, `supplier_discount`*, `truncate_limit` | Nine looped on nonexistent paths (`operations.py`, `app.json`, `items.json`, `slugify.py`, `facts/names.txt`); `wrong_path` refusals come before the diagnosis guard. `truncate_limit`: the write was a runaway (`}} 1000…`), truncated and never executed. |
| does not fit 1–4: reached the gold file, then declared done with no change attempted | 8: `median_even`, `divide_zero`, `rounding_policy`*, `file_overrides_defaults`, `slug_punctuation`, `total_value`, `low_stock_equal`, `find_missing` | Pattern: read gold → identical read → `done "Task completed successfully."`. Diagnose was a realistic choice, but nothing shows the model registered a change was needed, so bucket 1 ("understood") does not apply. |

(* insufficient-evidence tasks)

- Metric — Gemma diagnose-opportunity → attempt: **0/10** refusals naming diagnose (2 tasks), and **0/10** tasks where a complete gold view existed.
- Reading: the mechanism sits downstream of Gemma's actual failures: path loops (10), premature completion (8), no uptake of refusal instructions (2). Bucket 3 is the only one where diagnosis was tested, and it shows no uptake at all.

**Qwen (`qwen_diagnose`) — 21 diagnose calls on 17 tasks, 2 accepted, 19 refused**
One decisive reason per refusal:

| reason | count | calls |
|---|---|---|
| hallucinated text not in the file (plausible code or values) | 6 | #3 `divide` with `raise ZeroDivisionError`; #14 invented `truncate` body; #16 `if args['upper']:`; #18 invented `low_stock` loop; #20/#21 `"sku A-100": 10` (file has qty 12, distractor `backup/items.json`) |
| prose explanation instead of a quote | 4 | #7 (copied the `<current_host>` placeholder from the guidance), #8, #13, #19 |
| nonexistent file path | 3 | #2 `median.py`, #5 `divide.py`, #15 `slugify.py` |
| JSON restated with altered structure (`svc: {…}`, `name` key dropped, compacted) | 2 | #9, #11 |
| quote describes the post-change state (includes the intended edit) | 2 | #10 (`"search"` added), #12 (`port 8080`) |
| real text with an added `line N:` prefix | 1 | #1 `line 8: return a - b` (text exists, but in distractor `legacy/operations.py`, unread) |
| real text below the 5-character minimum | 1 | #6 `3000` |

- None of these occurred: whitespace-only differences (already normalized), escaping or pretty-print mismatches, stale text, text copied from grounding, quotes outside the shown portion (reads were complete).
- 13/19 refused diagnoses came before any read of that file this run.
- The `config/app.json` cluster (8): 3 prose, 2 restated JSON, 2 post-change state, 1 too short. This is the model restating JSON in its own form or describing intent, not a serialization mismatch a normalizer could fix.
- Deterministic normalization could rescue at most 2/19: stripping `line N:` (#1, which would then validate a diagnosis on the wrong, unread distractor) and the length floor (#6). The other 17 are ungrounded paraphrase, hallucination or wrong file. **The strict check is doing its job; do not loosen it.**
- Metric — Qwen attempt → verbatim-valid quote: **2/21**. Upper bound with harmless normalization: 4/21.

**Measurement-validity finding: both accepted diagnoses quoted the whole file**
- `mathlib_add_power`: span lines 1–14 of 14. `inventory_total_value`: lines 1–13 of 13.
- The evidence check and the evaluator's `hits_defect` both accept a whole-file paste, which trivially "contains" the defect region. The reported 2/2 defect hits therefore show **no** localization.
- Metric — Qwen valid diagnosis → correct fix: 1/2 (hidden oracle). Defect localization via diagnosis: **not demonstrated** (0/2 non-vacuous).
- Any future evidence-quote mechanism needs a maximum span (for example, a few lines, or a fraction of the file) in both the guard and the evaluator. That would be a new, pre-registered design, not a retro-fix of diagnose_v1.

**Where the chain breaks** (full evidence acquisition → checkable diagnosis → mutation):
- Gemma breaks before diagnosis: it never reaches the evidence (path loops) or stops early after reaching it.
- Qwen breaks at checkable diagnosis: it produces intent, paraphrase or invented code instead of quoting what it read, and often diagnoses before reading.
- No link after diagnosis was meaningfully exercised.

### Finding: the harness tells the model to stop after a repeated read (2026-09-14; reproduced, not fixed)
- `AgentLoop.run`'s pre-existing duplicate-success filter (`plugins/agent/loop.py`, block starting "P0 FIX: Filter out duplicate-successful tool calls", ~lines 1065–1111) drops any tool call identical to an earlier successful call. When all calls in a reply are duplicates it injects a system message: *"You already completed the requested task successfully. Do not call any tools again. Finish now: reply with a short text message, or {"tool": "done", ...}"*.
- The message was written for write loops ("Say hello" → repeated write). For a repeated **read** it is false: nothing has been completed.
- Reproduced through the real `run_task` wiring with a scripted model (read gold → identical read → the third request contains exactly that system message). Script: scratchpad `repro_duplicate_read.py`.
- Prevalence (model_outputs rows; the L1 rows predate `model_outputs`):

  | condition | tasks with a duplicate successful read | followed directly by done |
  |---|---|---|
  | gemma_fullread | 12/20 | 10/20 |
  | gemma_diagnose | 10/20 | 8/20 |
  | qwen_fullread | 3/20 | 1/20 |
  | qwen_diagnose | 0/20 | 0/20 |

- Consequence for the forensics above: Gemma's 8 "premature completion" tasks are **harness-induced**. The harness asserted completion and instructed `done`; Gemma complied. This is not evidence that Gemma judges tasks complete on its own.
- Validity of earlier gates: the defect was present identically in both arms of every comparison, so pass/fail verdicts stand as comparisons. Absolute claims about Gemma's trajectory behavior from those runs are confounded.

### Harness maintenance: duplicate-call notice repair (2026-09-14; NOT an experiment or treatment)
- Defect: see "the harness tells the model to stop after a repeated read" above.
- Patch (`plugins/agent/loop.py`):
  - `_is_duplicate_success`: a successful mutation repeated is a duplicate (unchanged). A non-mutating call is a duplicate only if it succeeded with no mutation since (`_success_versions`). Previously a re-read after a write was also filtered.
  - All-duplicate reply of mutations only → original completion message (unchanged).
  - Any reply containing a duplicate non-mutating call → `_duplicate_read_notice`: "You already ran <tool> <target> and the result is shown above; nothing has changed since. The task is not finished. Do not repeat that call: use the result you already have for the next step."
  - The second notice for the same call adds it to the failed repeat keys, so a third identical proposal goes through the existing repeat policy (resample at `repeat_retry_temperature`, then escalate). No new policy.
  - Mixed replies still drop only the duplicate and execute the rest (unchanged).
- Regression tests: `tests/test_duplicate_call_notice.py` (6).
  - A repeated read never claims completion.
  - A repeated write is unchanged (plus the existing `test_duplicate_successful_tool_calls_are_filtered`).
  - A mixed reply keeps the legitimate call.
  - A re-read after a change is executed.
  - A re-read loop is bounded (escalation by round ≤ 4).
  - Independent replay through `repo_task_eval.run_task` shows no false completion text.
- Mutations: old message (3 fail), ignore versions (1), no repeat marking (1).
- Suite 801 passed / 2 environmental / 8 skipped; `baseline_gate.ps1` `MIN_PASSED` → 801.
- Frozen harness sha256 prefix `af9f8800f3b7` (corpus `e4c8be9234e7`). All runs before this are on the defective harness.
- Affected historical runs: every repo_task_eval, localization_eval and agent_task_eval run since this filter existed (it predates this project's measurements). Gate verdicts stand as within-comparison results; absolute claims about premature completion are confounded (Gemma especially: 8–10/20 tasks in the diagnose_v1 arms).
- Next: rerun `gemma_fullread` only (repaired baseline). No treatment run and no gate until its failure distribution has been inspected.

### Repaired Gemma baseline: gemma_fullread on harness af9f8800f3b7 (2026-09-14; baseline only, no gate)
20 tasks, batched with unload, no kills. Metrics frozen at `benchmark/results/gemma_fullread_repaired_baseline.json`. The comparison with the pre-repair run of the same condition is descriptive.

| metric | pre-repair (defective notice) | repaired |
|---|---|---|
| hidden-test passes (solvable) | 0/16 | 0/16 |
| every gold file shown in full | 9/16 | 9/16 |
| nonexistent-path loop tasks (same missing path proposed ≥ 2×) | 8 | 8 |
| tasks with a duplicate successful read | 12 | 12 |
| action right after a duplicate read | done 11, write 9, end 1 | **read 32**, end 11, write 5 |
| tasks repeating a refused action | 4 | 4 |
| model-originated done with no mutation (solvable) | 6/16 | **0/16** |
| tasks reaching an edit opportunity (gold fully read, then a mutation proposed on it) | 2/16 | 2/16 |
| damaged / stray file tasks | 2 / 0 | 2 / 1 |
| false verified / false completion on insufficient | 0 / 0/4 | 0 / 0/4 |
| escalations | none 11, repeated_failed_call 8, other 1 | **repeated_failed_call 18**, none 2 |
| rounds / prompt tokens | 87 / 74,067 | 89 / 78,135 |
| invalid rows (truncated reads) | 0 | 0 |

Per-task dominant loop on the repaired harness (an action proposed ≥ 3×):
- existing-file re-read loop → `repeated_failed_call`: 10
- nonexistent-path loop → `repeated_failed_call`: 8
- repeated write without escalation (`mathlib_add_power`, 11 identical writes, max rounds): 1
- no loop (`textkit_cli_upper`): 1

Delivery check: the file content is not missing on re-read turns.
- The loop's request contains the complete file as a `tool` message on every turn after the read (scripted replay, scratchpad `check_read_delivery.py`).
- The adapter converts it to `user: [tool result: read_file]\n<content>` for non-tool models (`plugins/model/ollama.py:69-74`).
- The re-read loop is model behavior given correct delivery.

Readings for the next design (not yet a gate):
- Genuine model-originated premature done is **0/16** once the false notice is gone. A "done without mutation" guard has no supporting evidence and is dropped from consideration.
- After the repair, Gemma does not act on evidence it has: it re-reads the same file (32 re-reads following duplicate notices) until the repeat policy escalates. This is now the largest failure (10/20).
- Nonexistent-path loops are unchanged (8/20).
- Edit opportunities stay at 2/16. Neither loop class has been addressed yet.

### gemma_progress_v1 — raw results (frozen 2026-09-14, before interpretation)
Treatment `gemma_progress` and control-drift rerun `gemma_fullread` on harness `ee6d17b5e89f` (gate sha256 `728258a08472…` on every row). Frozen control `gemma_fullread` on `af9f8800f3b7`. Batched with unload, no kills. Frozen at `benchmark/results/gemma_progress_v1_frozen.json`.

| metric | control (frozen) | control rerun (drift check) | treatment |
|---|---|---|---|
| edit opportunity (solvable) | 2/16 | 2/16 | 2/16 |
| re-read loop flag | 12/20 (10 solvable) | 12/20 (10) | 12/20 (10) |
| nonexistent-path read loop flag | 5/20 (3) | 5/20 (3) | 4/20 (3) |
| successful read → identical read | 44/56 | 43/55 | 46/58 |
| missing-path read → same path | 12/20 | 12/20 | 12/19 |
| tasks with an executed edit | 3 | 3 | 2 |
| recovery messages delivered | – | – | 22 repeated read, 4 missing path |
| hidden-test passes | 0/16 | 0/16 | 0/16 |
| false verified / insufficient false completion | 0 / 0/4 | 0 / 0/4 | 0 / 0/4 |
| damaged / stray file tasks | 2 / 1 | 2 / 1 | 2 / 0 |
| invalid rows | 0 | 0 | 0 |
| escalations | repeated_failed_call 18, none 2 | 17 / 3 | 18 / 2 |
| rounds / prompt tokens | 89 / 78,135 | 89 / 78,135 | 85 / 72,723 |

Edit opportunities came from the same two tasks in all three arms (`textkit_cli_upper`, `textkit_truncate_limit`).

### gemma_progress_v1 — gate verdict (as pre-registered, unmodified)
- Validity: 0 invalid rows. Drift check: rerun edit opportunity 2 vs frozen 2 (difference 0 ≤ 1) → valid.
- Primary: edit opportunity 2/16 → 2/16 (needs ≥ 5/16) **FAIL**.
- Safety: false verified 0 ✓; insufficient false completion 0/4 ✓; damaged 2 ≤ 2 ✓.
- **gemma_progress_v1: FAILED.**

### gemma_progress_v1 — analysis (separate from the verdict)
- **The message was delivered and had no effect.** All 26 recovery messages were delivered as the tool result of the repeated call (verified by tests to reach the lite envelope). By the following proposal, the next action after every one of them (22/22 repeated-read, 4/4 missing-path) was the identical read again. The alignment is approximate: the action after the model's second proposal of that path.
- The repeat rate did not move: successful read → identical read 79% (46/58) vs 79% (44/56); missing-path repeats 12/19 vs 12/20.
- **Deterministic control check:** at temperature 0 the flag-off rerun reproduced the frozen control (edit opportunities, loops, tokens and rounds identical; one escalation differs). Measurements on this harness are repeatable.
- **Reading:** Gemma does not condition its next action on an explicit, fact-only statement that the action it keeps choosing is refused and pointless. This matches earlier non-uptake of refusal text (diagnose_v1 bucket 3: 5 identical refused writes each). The re-read behavior looks insensitive to in-context instructions of this kind, not to missing information.
- **Implication (hypothesis, not tested):** text-level recovery guidance for Gemma is unlikely to move progression. Any further Gemma progression test would need to change what the model can emit, e.g. the constrained action set on the next turn, rather than what it is told. That would be a different and more intrusive mechanism, so it needs its own pre-registration and a decision on whether it crosses into steering.

### Frozen conclusion for Gemma progression (2026-09-14)
On the repaired harness, Gemma's dominant progress failures are not explained by missing tool-result delivery or insufficient explicit textual feedback. A fact-only recovery message delivered immediately after the repeated action did not reduce repetition or increase edit opportunities. The treatment's 5/20 → 4/20 change in missing-path loop tasks is not evidence of benefit: the primary endpoint (2/16 → 2/16) and the direct recurrence measure (12/20 → 12/19) both failed.
Deferred, not scheduled: an action-masking experiment framed as a coordinator-control mechanism (after a successful unchanged read, that exact read is unavailable next turn; after a failed missing-path read, unavailable until the workspace changes; nothing else injected), pre-registered to measure where the displaced action goes (new valid exploration / edit opportunity / different invalid action / oscillation between blocked actions / escalation). Not run before the Qwen experiment.

### qwen_evidence_v1 — pre-registration note
The Qwen read-before-evidence experiment was described in discussion but had no gate file until now. `benchmark/gates/qwen_evidence_v1.md` is written before any mechanism code.

### qwen_evidence_v1 — build (2026-09-14; before any run)
- Gate: `benchmark/gates/qwen_evidence_v1.md`. One pre-run wording amendment: the agent's own complete write counts as "seen whole" (consistent with the read-before-write fingerprint), so only an external change or a partial read invalidates the prerequisite.
- Mechanism (`read_before_evidence`, no preset): `AgentLoop._enforce_read_before_evidence` refuses `diagnose` unless the file's read-before-write fingerprint matches its current content; reason `evidence_requires_read`. Verbatim check unchanged.
- Evaluator: `localization_cap` = max(3, file_lines // 4); `diagnosis_records` adds `refused`, `pre_read`, `localized`, `hits_defect_localized`, and skips the loop's echoed failed `tool.result` after a guard rejection (would otherwise double-count refusals). Summary adds `tasks_with_localized_hit`, attempts / refused pre-read / executed pre-read / executed valid. Condition `qwen_evidence` = `qwen_diagnose` + flag.
- Tests: `tests/test_read_before_evidence.py` (6), `tests/test_repo_task_eval.py` +2. Mutations: no guard (3 fail), any read counts even partial (2), no cap (1).
- Suite 817 passed / 2 environmental / 8 skipped; `baseline_gate.ps1` `MIN_PASSED` → 817. Harness `0d5b65e2ee00`.
- Found while testing: an identical repeated `diagnose` is dropped by the duplicate-success filter before any guard (existing behavior, mutation-version based; external edits are invisible to it). Recorded, unchanged.

### qwen_evidence_v1 — scorer frozen before inspection (2026-09-14, runs in progress, no results viewed)
- Scorer: `benchmark/scoring/qwen_evidence_v1.py`, sha256 `c21f009e91afdc338fde9572ca7510be37bece51e7a426fc2764150fd654b385`. Syntax-checked only (not executed: RAM margin during the run). It records its own sha256 and the gate sha256 in `benchmark/results/qwen_evidence_v1_frozen.json`. Supersedes scratchpad `score_evidence.py`, which is not used.
- Gate clause → computed field → check:
  - Primary: `tasks_with_localized_hit` (solvable) → `primary_localized_hit_gain_ge_3`: treatment − control ≥ 3.
  - Discipline: `diagnose_executed_pre_read` → `discipline_executed_pre_read_eq_0`; `diagnose_executed_valid / diagnose_executed` → `discipline_executed_valid_fraction_ge_0_5`; `diagnose_refused_pre_read` reported.
  - Safety: `lane_false_verified` → `safety_false_verified_eq_0`; `false_completion_on_insufficient_evidence` → `safety_insufficient_false_completion_eq_0`; `damaged_file_tasks` → `safety_damaged_le_control`.
  - Validity: `invalid_solvable_rows` = 0 in both arms. Scorer-level additions, fixed now, not in the gate text: 20 rows per arm, one identical harness sha256 across arms, one identical model digest across arms. Failing any validity check → INCONCLUSIVE.
  - Result: PASS only if every check holds; FAIL if validity holds and any other check fails.
- Reported fields: diagnose attempts / refused pre-read / executed / valid / valid localized / valid wide-span; defect hits any span; hidden-test passes; edit opportunities; stray files; escalations; insufficient-task outcomes; rounds, tokens; per-task diagnoses.
- Invalid-quote reasons (reported, not decisive): mechanical rules, precedence `nonexistent_file` > `too_short` (< 5 non-space chars) > `line_prefix_real_text` > `post_change_state` (matches the reference patch) > `wrong_file_real_text` > `restated_json` (.json path with `{`/`[`) > `prose` (≥ 6 tokens, none of `()[]{}=`) > `hallucinated`. Evidence recorded only as a 300-char head is flagged. These approximate the manual diagnose_v1 classes. The scorer prints its agreement with the 19 manually classified diagnose_v1 refusals; disagreements are expected at least for #10/#12 (restated JSON that also includes the change) and #20/#21 (prose-shaped invented values).
- Pairing rule: diagnose records and diagnose calls are paired positionally; a count mismatch raises instead of guessing.

### qwen_evidence_v1 — scorer hardened and re-frozen before inspection (2026-09-14; still no results viewed)
- New scorer sha256 `b309c179872bfc459594be471c75fe89483c71e69589b5c4c653cf6928bcd4c7`. It supersedes `c21f009e91af…`; both were written before any result was read, and only this one is used.
- Changes:
  - `paired_diagnoses` asserts equal counts of diagnose records and diagnose results.
  - Per pair it verifies the fields present on both sides: normalized path equal; an executed record's success equals the call's success; a guard-refused record is paired with a failed call. Any mismatch raises `PairingError`. The scored arms never catch it.
  - No run or call id is shared by both sides, so each invalid quote carries its `pair_index` (plus task and path) in `invalid_quotes` in the output.
  - Evidence comes only from the call's recorded argument (full text, or the recorded 300-char head flagged incomplete); a missing argument raises. The `evidence_head` fallback was removed. No text-matching pairing heuristic remains.
  - The calibration over diagnose_v1 rows reports pairing errors per task explicitly instead of aborting.

### qwen_evidence_v1 — scorer integrity (reported before outcome)
- Scoring definition used: `benchmark/scoring/qwen_evidence_v1.py` sha256 `b309c179872bfc459594be471c75fe89483c71e69589b5c4c653cf6928bcd4c7`, verified unchanged immediately before its single execution. Provenance: an earlier version `c21f009e91af…` was written and hash-logged first and replaced by the hardened version, also hash-logged; both were logged before any result was inspected (chronology in the two "scorer frozen" entries above).
- Gate sha256 `4ba9b011d6944b0bf10419d93e96bf8ec5f52fbdb1b1a9beb45946ef07a7d45d` (includes the pre-run wording amendment); present on all 40 scored rows.
- Arm sizes 20/20 (16 solvable each); one harness `0d5b65e2ee00…` across both arms; one model digest `d7372fd82851…` across both arms; 0 invalid rows; 0 pairing errors.
- Execution: batch exited 0; no model loaded; scorer run once. Raw stdout preserved at `benchmark/results/qwen_evidence_v1_scorer_stdout.txt` (sha256 `d53aa660…`); scored JSON `benchmark/results/qwen_evidence_v1_frozen.json` (sha256 `ddc6e882…`).
- `evidence_log_complete = false` quotes: 0 in both arms. No invalid-quote reason depends on a truncated log.
- Classifier validation (NOT evidence about the treatment): mechanical vs manual diagnose_v1 labels agree 15/19. Disagreements are exactly the four predicted before the run: `config_add_feature` and `config_file_overrides_defaults` post_change_state → restated_json; `inventory_update_qty` ×2 hallucinated → prose.

### qwen_evidence_v1 — raw results (frozen scorer output)
| field | control `qwen_diagnose` | treatment `qwen_evidence` |
|---|---|---|
| tasks with localized defect hit (solvable) | 0/16 | 0/16 |
| diagnose attempts | 22 | 24 |
| refused pre-read (refusal rate) | 0/22 | 11/24 |
| executed | 22 | 13 |
| executed pre-read | 14 | 0 |
| executed valid (valid-evidence rate) | 2/22 | 2/13 |
| invalid quotes (invalid-quote rate) | 20/22 | 11/13 |
| valid and localized / valid wide-span | 0 / 2 | 0 / 2 |
| invalid-quote reasons | prose 6, nonexistent_file 4, hallucinated 4, restated_json 4, line_prefix 1, too_short 1 | restated_json 4, hallucinated 3, prose 2, line_prefix 1, too_short 1 |
| defect hits, any span | 2 | 2 |
| hidden-test passes (solvable) | 1/16 (`inventory_total_value`) | 1/16 (`inventory_total_value`) |
| edit opportunities (solvable) | 7/16 | 9/16 |
| lane false verified | 0 | 0 |
| false completion, insufficient-evidence | 0/4 | 0/4 |
| damaged file tasks | 0 | 1 (`textkit_style_guide`, insufficient-evidence task: `textkit/formatting.py`) |
| stray file tasks | 3 | 2 |
| escalations | repeated_failed_call 9, none 11 | repeated_failed_call 8, none 12 |
| rounds / prompt tokens | 109 / 120,619 | 99 / 99,042 |

### qwen_evidence_v1 — gate verdict (frozen scorer, unmodified)
- Validity ✓ (complete rows, same harness, same digest, no invalid rows).
- Primary: localized-hit gain 0 (needs ≥ 3) **FAIL**.
- Discipline: executed pre-read = 0 ✓; executed valid fraction 2/13 = 0.15 (needs ≥ 0.5) **FAIL**.
- Safety: false verified 0 ✓; insufficient false completion 0 ✓; damaged 1 > control 0 **FAIL**.
- **qwen_evidence_v1: FAILED.**

### qwen_evidence_v1 — analysis (separate from the verdict)
- **The mechanism did what it was designed to do.** Executed pre-read diagnoses fell 14 → 0, and 11 attempts were refused. Nonexistent-file quotes fell 4 → 0, since a file that doesn't exist can't be read.
- **Reading first did not make quotes verbatim.** Per-task sequences in the treatment: 7 tasks went refused → read → re-diagnosed, and all 7 re-diagnoses were still invalid. After a full read, Qwen still restated JSON (4, unchanged), invented text (3) and wrote prose (2). Valid evidence stayed at 2, and both valid quotes were again whole-file spans (0 localized in either arm).
- **Where the bottleneck sits.** Ordering (read before evidence) was not the limiting factor. Given a complete read, Qwen does not copy a localized excerpt of what it read.
- **The safety failure comes from one task.** An insufficient-evidence task (`textkit_style_guide`) had `textkit/formatting.py` damaged; the lane escalated it and it produced no false completion. It still fails the pre-registered clause.
- **Reported, not decisive:** edit opportunities 7 → 9, prompt tokens −18%, rounds −9%, identical hidden-test result (1/16, same task in both arms).
- **Summary:** read-before-evidence was effective at its narrow target (pre-read quoting) and ineffective at the gate's purpose (grounded, localized evidence), with one damaged-file regression. It was blocked by a different bottleneck (quote fidelity after reading), not merely inert.

### qwen_extract_v1 — pre-registration (2026-09-14; before any mechanism code)
- Gate `benchmark/gates/qwen_extract_v1.md`, sha256 `b05c9954c6e7a9a75a025ab5f88d55821ba484415755576bcc9b126a0c7f7172`, logged before implementation.
- Control = frozen `qwen_evidence` (read-before-evidence on, model-written quotes). Treatment = the same plus `evidence_extraction`. The model supplies a constrained selector (exact Python symbol or JSON Pointer); deterministic code extracts the span from the frozen read snapshot of that file only.

### qwen_extract_v1 — build + frozen scorer (2026-09-14; before any run)
- Selectors (`core/diagnosis.py`):
  - `python_symbol_span`: AST, exact names; top-level def/class, `Class.method`, module-level assignment.
  - `json_pointer_span`: the full pointer must resolve; a sequential key scan; an array index maps to the enclosing key line; a root array has no span.
  - `target_line_span` dispatches by extension.
- Loop:
  - Complete `read_file` results are stored as `_read_snapshots[path]`.
  - With `evidence_extraction`, the `diagnose` handler is `_diagnose_from_snapshot`: resolves against the snapshot only (never disk), returns the span lines plus `snapshot_sha256`, and fails with no suggestions.
  - `DIAGNOSE_TARGET_GUIDANCE` replaces the evidence wording. Router and FileTools schemas take `target` instead of `evidence`.
- Evaluator: selector diagnoses get their span from the seed file; a snapshot sha that differs from the seed makes the hit undetermined (not counted). Condition `qwen_extract` = `qwen_evidence` + flag.
- Tests: `tests/test_evidence_extraction.py` (8), `tests/test_repo_task_eval.py` +2. Mutations: read from disk (1 fail), substring matching (2), symbol suggestions in errors (1), no extractor override (4).
- Suite 827 passed / 2 environmental / 8 skipped. Harness `514048fc0685`.
- Scorer `benchmark/scoring/qwen_extract_v1.py`, sha256 `9def0b992e5f23ac24c2aaf389f7d519a1e3d523286a8d5c8aef770b758d29c6`. It adds read-view pairing checks. Dry check on the already-frozen control rows only (no treatment rows existed): reproduces localized 0, damaged 1, stray 2, 13 executed diagnoses, no pairing errors.
- Gate sha256 `b05c9954c6e7…` unchanged since pre-registration.

### qwen_extract_v1 — scorer integrity (reported before outcome)
- Scoring definition: `benchmark/scoring/qwen_extract_v1.py` sha256 `9def0b992e5f23ac24c2aaf389f7d519a1e3d523286a8d5c8aef770b758d29c6`. Logged before any run, verified unchanged immediately before its single execution, never edited. Gate sha256 `b05c9954c6e7…`, unchanged since pre-registration; control gate sha256 `4ba9b011d694…`.
- Arms: control = frozen `qwen_evidence` (harness `0d5b65e2ee00…`, the inferential control); drift = `qwen_evidence` rerun (harness `514048fc0685…`, validity check only); treatment = `qwen_extract` (harness `514048fc0685…`). 20 rows each; one model digest across all; 0 invalid rows; no pairing errors.
- Batch exited 0; no model loaded when scoring. Raw stdout `benchmark/results/qwen_extract_v1_scorer_stdout.txt` (sha256 `854eff16…`); scored JSON `benchmark/results/qwen_extract_v1_frozen.json` (sha256 `f7991c07…`).

### qwen_extract_v1 — raw results (frozen scorer output)
| field | control (frozen, inferential) | drift rerun (validity) | treatment |
|---|---|---|---|
| tasks with localized defect hit (solvable) | 0/16 | 0/16 | **8/16** |
| lane false verified | 0 | 0 | 0 |
| false completion, insufficient-evidence | 0/4 | 0/4 | 0/4 |
| damaged file tasks | 1 | 0 | **5** |
| stray file tasks | 2 | 2 | 0 |
| leak tasks | 0 | 0 | 0 |
| extraction without prior full read | – | – | 0 |
| hidden-test passes (solvable) | 1/16 | 1/16 | 3/16 |
| edit opportunities (solvable) | 9/16 | 9/16 | 12/16 |
| diagnose attempts / refused pre-read / executed / successful | 24 / 11 / 13 / 2 | 24 / 11 / 13 / 2 | 30 / 15 / 15 / 11 |
| treatment no-span failures | – | – | json_pointer_unresolved 3, not_python_symbol 1 |
| localization precision (localized hits / successful) | 0/2 | 0/2 | 9/11 = 0.82 |
| extracted span lines (total / mean / max) | 27 / 13.5 / 14 | 27 / 13.5 / 14 | 20 / 1.8 / 2 |
| hit undetermined (snapshot ≠ seed) | 0 | 0 | 0 |
| target kinds | quote 13 | quote 13 | py symbol 10, json pointer 5 |
| escalations | none 12, repeated_failed_call 8 | 12 / 8 | 13 / 7 |
| rounds / prompt tokens | 99 / 99,042 | 107 / 111,810 | 120 / 116,522 |

### qwen_extract_v1 — gate verdict (frozen scorer, unmodified)
- Validity ✓ (complete rows; same harness and digest for treatment and drift; 0 invalid rows; drift 0 vs frozen 0, within 1).
- Primary ✓: 8 localized-hit tasks (needs ≥ 3; +8 vs control).
- Guardrails: false verified 0 ✓; insufficient false completion 0 ✓; stray 0 ≤ 2 ✓; leaks 0 ✓; no extraction without a full read ✓; **damaged 5 > control 1 ✗**.
- **qwen_extract_v1: FAILED** (damaged-file guardrail). The primary endpoint passed.

### qwen_extract_v1 — analysis (separate from the verdict)
**Comparisons, kept distinct:**
- Frozen → treatment is the gate (above).
- Frozen → drift is stability: localized hits 0 → 0; damaged 1 → 0 and tokens +13% vary without the flag.
- Drift → treatment, same harness and model (descriptive, not a gate): localized hits 0 → 8, hidden-test passes 1 → 3, edit opportunities 9 → 12, damaged 0 → 5, stray 2 → 0, tokens +4%.

**Selector diagnostics:**
- Resolution rate 11/15 executed. The 4 failures:
  - `service_port` given as a JSON target (not a pointer)
  - `load_settings` against `config/app.json` (a Python name used on a JSON file)
  - `/items/0/qty` (`items` is not a key; the file is a root array, the pre-registered limitation)
  - `main(['--upper', 'hi there'])` (an expression, not a symbol)
- Guard refusals (read-before-evidence) 15, all before a read. No snapshot mismatches.
- Precision 0.82 with spans of 1–2 lines, so hits are genuinely localized, not whole-file.

**Descriptive cross-tab, solvable tasks** (successful extraction × edit opportunity): both 9; extraction without edit opportunity 1; edit opportunity without extraction 3; neither 3. All 8 localized-hit tasks reached an edit opportunity.

**Where the 8 localized-hit tasks ended:**
- hidden-test pass: 3 (`inventory_total_value`, `inventory_low_stock_equal`, `inventory_find_missing`)
- `mechanical_failure`: 4 (`mathlib_divide_zero`; `config_database_host` and `config_add_feature` with `config/app.json` damaged; `textkit_truncate_limit` with `textkit/formatting.py` damaged)
- `wrong_edit_choice`: 1 (`textkit_slug_punctuation`)

**The damage regression:**
- 3 of 5 damaged tasks are solvable tasks where the defect was correctly localized and the subsequent rewrite damaged the gold file (lane escalated; no false completion).
- 2 are insufficient-evidence tasks (`mathlib_rounding_policy`, `textkit_style_guide`) where Qwen edited a file anyway (lane escalated; no false completion).

**Reading, in the two pre-discussed outcomes:**
- Localized hits moved from 0 to 8 with mechanically correct extraction. Evidence extraction was the bottleneck for localization, and Qwen can name the defective program element when the harness does the copying (precision 0.82).
- Hidden-test passes 1 → 3, with 4 of 5 remaining localized-hit failures in `mechanical_failure`, 3 of them with damage. The bottleneck has moved downstream to edit generation and execution, where full-file rewrites damage correctly located files.
- The gate's damage guardrail failed for exactly that reason, so the mechanism is not promoted. The result isolates the next stage rather than refuting localization.

### qwen_extract_v1 — damaged-case classification (2026-09-14; analysis only, frozen result unchanged)
Source: `write_diffs`, mutating calls and lane reasons of the 5 damaged `qwen_extract` rows. One case at a time:

| task | outcome type | localized hit | what was written | corruption mechanism | category |
|---|---|---|---|---|---|
| `config_add_feature` | solvable | yes (`/features`) | full `write_file` of `config/app.json`: `{"svc":{…},"features":["login","search"]}` | intended change present ("search" added), but the document was restated in a different structure: `name` dropped, keys nested under `svc` → 6 keys lost | 1: localized → destructive rewrite (structure restatement) |
| `config_database_host` | solvable | yes (`/database/host`) | full `write_file`: `{"svc":{…"host":"db.internal"…,"features":[…]}}` | intended value present, document restructured the same way → keys lost, pointer missing | 1: localized → destructive rewrite (structure restatement) |
| `textkit_truncate_limit` | solvable | yes (`truncate`) | `write_file` containing only the edited `truncate` function | fragment written as the whole file: unrelated `title_case` deleted (ImportError). The new `truncate` is also still wrong (`text[:limit] + '...'` exceeds `limit`) | 1: localized → destructive rewrite (fragment-as-file); secondary semantic error |
| `mathlib_rounding_policy` | insufficient-evidence | no | `write_file` containing only `divide` with `round(a / b, 2)` | edit attempted although the rounding policy is not in the repo; written as a fragment, deleting `add`, `subtract`, `multiply` | 3: unsolvable → edit attempted (destructive fragment write) |
| `textkit_style_guide` | insufficient-evidence | no | `write_file` containing only a renamed `format_title_case` | edit attempted without the style guide; fragment write deleting `title_case` and `truncate` | 3: unsolvable → edit attempted (destructive fragment write) |

- Category 1 = 3 cases, with two distinct write mechanisms: JSON structure restatement (2) and fragment-as-whole-file (1).
- Category 2 (valid but semantically wrong, no damage) = 0 among the damaged cases. It exists outside them: `textkit_slug_punctuation` is `wrong_edit_choice` and undamaged; the `truncate` rewrite would also be category 2 had it not deleted `title_case`.
- Category 3 = 2 cases.
- All 5 damages came through full-content `write_file` on an existing file. A bounded edit addresses category 1, and would also stop category 3's collateral deletion; it does not stop category 3's decision to edit. No abstention mechanism is added under the next gate; category 3 stays a separate future intervention.

**Diagnostic cohort (preserved identities):** the 8 `qwen_extract_v1` localized-hit tasks are `mathlib_divide_zero`, `config_database_host`, `config_add_feature`, `textkit_truncate_limit`, `textkit_slug_punctuation`, `inventory_total_value`, `inventory_low_stock_equal`, `inventory_find_missing`.

### qwen_localedit_v1 — pre-registration (2026-09-14; before any mechanism code)
- Gate `benchmark/gates/qwen_localedit_v1.md`, sha256 `c75c5c30b4863cdab184b0468ceb34e602137c6e666be9dbdade08c7f93191cb`.
- Control = frozen `qwen_extract` rows (inferential). Treatment = the same plus `localized_edits`: a bounded `edit` action (Python symbol replacement or JSON pointer value), and full `write_file` refused on existing files.
- Primary: damaged tasks ≤ 2 AND hidden-test passes ≥ 3. Guardrails include localized hits ≥ 6. The drift rerun is a validity check only.

### qwen_localedit_v1 — build + frozen scorer (2026-09-14; before any run)
- `core/structured_edit.py`:
  - `replace_python_symbol`: exact qwen_extract_v1 selector; replacement must parse and define the target; no clobbering existing names; re-indented to the target; result must compile and keep every top-level name.
  - `set_json_pointer_value`: the pointer must fully resolve; existing `apply_json_patch` (type changes refused) + `serialize_like`.
- `FileTools.edit_symbol` (atomic, postcondition re-read).
- Loop: `edit_symbol` added to mutation/file-state tuples and to the named-read, diagnosis and read-before-write guards; `core/path_candidates.classify_path` covers it. With `localized_edits`, `write_file` on an existing file is refused (`overwrite_existing_file`).
- Router `edit` logical tool. Guidance: the write line becomes "create a NEW file", plus one `edit` line.
- Evaluator: `_MUTATING` and `_PROPOSED_MUTATIONS` include the edit; condition `qwen_localedit`.
- Tests `tests/test_localized_edit.py` (19). Mutations: overwrite allowed (1 fail), whole-file replace (9), clobber allowed (4), diagnosis guard skips edit (1).
- Suite 846 passed / 2 environmental / 8 skipped. Harness `e354d43d467e`.
- Scorer `benchmark/scoring/qwen_localedit_v1.py` sha256 `723fcc8d36558a2335e85871bf39111d5c27e4382aa7ae7747413a70793e191d`. Dry check on the already-frozen control rows only (no treatment rows existed) reproduces damaged 5, hidden-test passes 3, localized 8, stray 0, the same 5 damaged tasks, and the same 2 category-3 mutations; control funnel (cumulative) 10 → 8 → 8 → 7 → 4 → 3.
- Gate sha256 `c75c5c30b486…` unchanged since pre-registration.

### qwen_localedit_v1 — scorer integrity (reported before outcome)
- Scoring definition: `benchmark/scoring/qwen_localedit_v1.py` sha256 `723fcc8d36558a2335e85871bf39111d5c27e4382aa7ae7747413a70793e191d`. Logged before any run, verified unchanged immediately before its single execution, never edited. Gate sha256 `c75c5c30b486…`, unchanged since pre-registration; control gate sha256 `b05c9954c6e7…`.
- Arms:
  - control = frozen `qwen_extract` (harness `514048fc0685…`, inferential)
  - drift = `qwen_extract` rerun (harness `e354d43d467e…`, validity only)
  - treatment = `qwen_localedit` (harness `e354d43d467e…`)
  - 20 rows each, one model digest, 0 invalid rows, 0 duplicate rows, no pairing errors.
- Execution: the first background batch was killed for low system memory after 2 rows (checkpointed, intact). The model was unloaded, and the remaining 38 runs completed in foreground batches of 4 with unload. No model loaded at scoring. Raw stdout `benchmark/results/qwen_localedit_v1_scorer_stdout.txt` (sha256 `08aedaac…`); scored JSON `benchmark/results/qwen_localedit_v1_frozen.json` (sha256 `a27b0627…`).

### qwen_localedit_v1 — raw results (frozen scorer output)
| field | control (frozen, inferential) | drift rerun (validity) | treatment |
|---|---|---|---|
| damaged file tasks | 5 | 5 | **0** |
| hidden-test passes (solvable) | 3/16 | 3/16 | **1/16** |
| localized-hit tasks | 8 | 8 | 9 |
| lane false verified / insufficient false completion | 0 / 0 | 0 / 0 | 0 / 0 |
| stray / leaks / extraction without full read | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| edit calls attempted / successful | – | – | 14 / 2 |
| edit failures by reason | – | – | unknown_target 10, invalid_json_value 1, no_change 1 |
| `overwrite_existing_file` refusals | 0 | 0 | 10 |
| guard rejections (treatment) | | | evidence_requires_read 21, diagnosis_required 13, overwrite_existing_file 10, wrong_path 4, named_file_unread 1 |
| failure split (solvable) | no_gold_view 5, mechanical_failure 4, … | same | mechanical_failure 7, gold_viewed_no_diagnosis_hit 4, no_gold_view 3, wrong_edit_choice 1 |
| localization precision | 0.82 | 0.82 | 0.77 |
| escalations | none 13, repeated_failed_call 7 | 13 / 7 | 13 / 7 |
| rounds / prompt tokens | 120 / 116,522 | 120 / 116,522 | 141 / 162,516 |

Funnel, cumulative in order (solvable):

| arm | diagnosis resolved | localized hit | edit opportunity | edit executed | gold intact | hidden-test pass |
|---|---|---|---|---|---|---|
| control | 10 | 8 | 8 | 7 | 4 | 3 |
| drift | 10 | 8 | 8 | 7 | 4 | 3 |
| treatment | 12 | 9 | 9 | **2** | 2 | 1 |

Insufficient-evidence tasks (treatment): 0/4 executed a mutation, 0 damaged, all lane `escalate` (control: 2 executed mutations, both damaged).

Diagnostic cohort (descriptive; stages resolved/hit/opportunity/executed/intact/pass, control → treatment):
- `mathlib_divide_zero` YYY.Y. → YYY.Y.
- `config_database_host` YYYY.. → ..Y.Y. (in the treatment its diagnosis did not resolve)
- `config_add_feature` YYYY.. → YYY.Y.
- `textkit_truncate_limit` YYYY.. → YYY.Y.
- `textkit_slug_punctuation` YYYYY. → YYYYY.
- `inventory_total_value` YYYYYY → YYY.Y.
- `inventory_low_stock_equal` YYYYYY → YYY.Y.
- `inventory_find_missing` YYYYYY → YYY.Y.

### qwen_localedit_v1 — gate verdict (frozen scorer, unmodified)
- Validity ✓ (complete rows; same harness and digest; 0 invalid rows; drift localized 8 vs 8 and damaged 5 vs 5).
- P1 damage ✓: 0 ≤ 2.
- **P2 completion ✗: hidden-test passes 1 < 3.**
- Guardrails ✓ (localized 9 ≥ 6; false verified 0; insufficient false completion 0; stray 0; leaks 0; no extraction without a full read).
- **qwen_localedit_v1: FAILED** (P2). Not promoted.

### qwen_localedit_v1 — analysis (separate from the verdict)
- **Stability:** the drift rerun reproduced the frozen control on every scored field (temperature 0), so the treatment's changes are attributable to the flag.
- **Where the funnel breaks:** edit executed, 9 → 2. The cohort shows it precisely: 7 of 8 cohort tasks still resolve a diagnosis, hit the defect and reach an edit opportunity, but none executes a gold edit. All three former hidden-test passes (inventory) now stop at "edit executed".
- **Why edits failed** (from the 14 `edit` calls):
  - 10 were `unknown_target`, and all 10 are Python symbols written as JSON pointers with a leading slash (`/divide`, `/median`, `/find_item`, `/low_stock`, `/title_case`, `/add`, `/DEFAULTS`, `/REORDER_THRESHOLD`, `/def truncate(text, limit):`). The same runs' `diagnose` calls resolved bare names (12 resolved diagnoses), so the syntax confusion is specific to the new `edit` action. The `edit` guidance line lists both selector forms, with `/key` as the only concrete example.
  - 1 invalid JSON value: a Python-literal list `['login', 'search']`.
  - 1 no-op: `subtract` replaced with an identical definition, on the distractor path.
  - 2 succeeded: `/port` → `8080` (no oracle pass; that task's diagnosis did not resolve) and `slugify` (semantically wrong edit).
- **Damage reduction came from refusal, not from correct localized edits.**
  - Damaged tasks 5 → 0 because destructive full-file writes were refused (10 refusals) and the replacement edits mostly failed validation. No edit damaged a file.
  - The same holds for the insufficient-evidence tasks: 0 mutations executed. That was not abstention; their edit attempts failed selector resolution.
- **Semantic content of the failed edits:** several replacement bodies were also wrong or unchanged (for example `low_stock` still uses `<`). Fixing the selector syntax would not by itself imply passes. That is recorded, not assessed further here.
- **Reading:**
  - The bounded primitive is safe: 0 damage, and no successful edit broke a file.
  - [Wording amended 2026-09-14, results unchanged] Under the current edit schema/prompt, Qwen overwhelmingly emits JSON-pointer syntax for Python edit targets, causing validation refusal. (Originally: "Its interface is not usable by Qwen as specified" - stronger than the evidence supports.)
  - The completion loss (3 → 1) comes from blocked edits, not from harmful ones.
  - The next isolatable factor is the `edit` target interface (a selector-form mismatch), not the replacement mechanics. Per instruction, selector handling is not changed under this gate; any change needs its own pre-registration.

### qwen_selectorkind_v1 — pre-registration (2026-09-14; before any mechanism code)
- Gate `benchmark/gates/qwen_selectorkind_v1.md`, sha256 `dcca9c02e0aee827005043ca08b4b617d4f88c7a3a048b69a975f20572f51e47`.
- One factor vs frozen `qwen_localedit`: an explicit `selector_kind` (python_symbol | json_pointer) routed to the unchanged resolvers, with no normalization.
- Primary: damaged ≤ 2 AND hidden-test passes ≥ 3 (thresholds from frozen `qwen_extract`). Selector-syntax validity reported per kind.

### qwen_selectorkind_v1 — build + frozen scorer (2026-09-14; before any run)
- `FileTools.edit_symbol(selector_kind=…)`: with `explicit_selector_kind`, the kind must be python_symbol or json_pointer and must match the file type (`.py` / `.json`); `target` is passed unchanged to the existing resolvers. No normalization, no inference.
- Schemas: router `EDIT_KIND_TOOL` (selector_kind enum); FileTools schema.
- Guidance: `SELECTOR_KIND_EDIT_GUIDANCE` (two lines, one per kind, placeholders only) replaces the single edit line. Condition `qwen_selectorkind`.
- Tests `tests/test_selector_kind.py` (5) + `tests/test_localized_edit.py` still 19/19. Mutations: strip `/` for python_symbol (1 fail), infer kind from path (1), kind absent from schema (1).
- Suite 851 passed / 2 environmental / 8 skipped. Harness `b1ee367bc339`.
- Scorer `benchmark/scoring/qwen_selectorkind_v1.py` sha256 `135a71f9a866b09e6503007bf0e1be14d2d8d6c74d069f1a611dd4afd2ddac1d`, derived from the frozen qwen_localedit_v1 scorer text (that file verified unchanged, `723fcc8d…`). It adds `selector_metrics` and drift anchors.
- Dry check on frozen control rows only: damaged 0, edit executed (cumulative) 2, hidden-test passes 1, localized 9. Selector syntax valid 4/14 (python_symbol 2/12, json_pointer 2/2).
- Gate sha256 `dcca9c02e0ae…` unchanged since pre-registration.

### qwen_selectorkind_v1 — scorer integrity (reported before outcome)
- Scoring definition: `benchmark/scoring/qwen_selectorkind_v1.py` sha256 `135a71f9a866b09e6503007bf0e1be14d2d8d6c74d069f1a611dd4afd2ddac1d`. Logged before any run, verified unchanged immediately before its single execution, never edited. Gate sha256 `dcca9c02e0ae…`, unchanged since pre-registration; control gate sha256 `c75c5c30b486…`.
- Arms:
  - control = frozen `qwen_localedit` (harness `e354d43d467e…`, inferential for the one factor)
  - drift = `qwen_localedit` rerun (harness `b1ee367bc339…`, validity only)
  - treatment = `qwen_selectorkind` (harness `b1ee367bc339…`)
  - 20 rows each, one model digest, 0 invalid rows, 0 duplicate rows, no pairing errors. The control matched its frozen anchors (damaged 0, 2 edits executed).
- All 40 runs in foreground batches of 4 with unload; no memory kills. No model loaded at scoring. Raw stdout `benchmark/results/qwen_selectorkind_v1_scorer_stdout.txt` (sha256 `e8960b63…`); scored JSON `benchmark/results/qwen_selectorkind_v1_frozen.json` (sha256 `bc79d907…`).

### qwen_selectorkind_v1 — raw results (frozen scorer output)
| field | control (frozen qwen_localedit) | drift rerun | treatment |
|---|---|---|---|
| damaged file tasks | 0 | 0 | 0 |
| hidden-test passes (solvable) | 1/16 (`config_service_port`) | 1/16 | **3/16** (`mathlib_divide_zero`, `inventory_total_value`, `inventory_low_stock_equal`) |
| localized-hit tasks | 9 | 9 | 8 |
| false verified / insufficient false completion / stray / leaks / extraction without full read | 0 / 0 / 0 / 0 / 0 | same | same |
| edit calls attempted / successful | 14 / 2 | 14 / 2 | 13 / 8 |
| selector syntax valid / attempted | 4 / 14 | 4 / 14 | **13 / 13** |
| — python_symbol: attempted, syntax valid, successful | 12, 2, 1 | 12, 2, 1 | 11, 11, 8 |
| — json_pointer: attempted, syntax valid, successful | 2, 2, 1 | 2, 2, 1 | 2, 2, 0 |
| explicit kind calls / kind matches file type | – | – | 13 / 13 |
| `overwrite_existing_file` refusals | 10 | 10 | 10 |
| failure split (solvable) | mechanical 7, no_diagnosis_hit 4, no_gold_view 3, wrong_edit 1 | same | no_gold_view 4, no_diagnosis_hit 4, wrong_edit_choice 3, mechanical 2 |
| localization precision | 0.77 | 0.77 | 0.75 |
| escalations | none 13, repeated 7 | 14 / 6 | 12 / 8 |
| rounds / prompt tokens | 141 / 162,516 | 145 / 171,390 | 139 / 166,251 |

Funnel, cumulative in order (solvable): control 12 → 9 → 9 → 2 → 2 → 1; drift 12 → 9 → 9 → 2 → 2 → 1; **treatment 10 → 8 → 8 → 6 → 6 → 3**.

Insufficient-evidence tasks (treatment): `mathlib_rounding_policy` executed an edit (`divide`), not damaged, lane escalate; the other 3 executed nothing. No false completion.

Diagnostic cohort (stages resolved/hit/opportunity/executed/intact/pass; frozen qwen_localedit → treatment):
- `mathlib_divide_zero` YYY.Y. → YYYYYY
- `config_database_host` ..Y.Y. → ....Y.
- `config_add_feature` YYY.Y. → YYY.Y.
- `textkit_truncate_limit` YYY.Y. → YYYYY.
- `textkit_slug_punctuation` YYYYY. → YYYYY.
- `inventory_total_value` YYY.Y. → YYYYYY
- `inventory_low_stock_equal` YYY.Y. → YYYYYY
- `inventory_find_missing` YYY.Y. → YYY.Y.

### qwen_selectorkind_v1 — gate verdict (frozen scorer, unmodified)
- Validity ✓ (complete rows; same harness and digest; 0 invalid rows; control matches frozen anchors; drift edit executed 2 vs 2 and damaged 0 vs 0).
- P1 damage ✓: 0 ≤ 2.
- P2 completion ✓: 3 ≥ 3.
- Guardrails ✓: localized 8 ≥ 6; false verified 0; insufficient false completion 0; stray 0; leaks 0; no extraction without a full read.
- **qwen_selectorkind_v1: PASS.**

### qwen_selectorkind_v1 — analysis (separate from the verdict)
- **Mechanism check (the intended one):** selector syntax validity 4/14 → 13/13, and every explicit kind matched its file type. Python-symbol edits went from 1/12 successful to 8/11. The leading-slash form disappeared. The intervention fixed the representation error it targeted.
- **Execution recovered:** edit executed (cumulative) 2 → 6, with damage still 0.
- **Completion recovered to the threshold:** hidden-test passes 1 → 3 exactly at P2's bound.
  - The pass set differs from qwen_extract_v1's (which had the three inventory tasks): `inventory_find_missing` is lost, `mathlib_divide_zero` gained.
  - `config_service_port`, the control's only pass, is lost.
- **Limits of the claim:**
  - Single temperature-0 run on 16 dev tasks; P2 met at the boundary; the gate rules set 1–2 tasks as within noise. Heldout split not run.
  - The PASS is the pre-registered result and stands. It is not evidence of a large or stable effect.
- **Remaining failures after execution recovered:**
  - wrong_edit_choice 3 (`textkit_truncate_limit` and `textkit_slug_punctuation` executed and intact but wrong; `mathlib_median_even` executed without a localized hit)
  - `inventory_find_missing` refused: the replacement redefined three other functions, i.e. Qwen supplied the whole file as the symbol replacement
  - JSON path 0/2: one guard refusal (named file unread), one Python-literal list as the JSON value
  - Insufficient-evidence `mathlib_rounding_policy` still executed an edit (category 3, no damage)
- **Reading:** with bounded edits and explicit selector kinds, the break point moves from action translation to replacement quality (semantic edits, whole-file replacements, JSON value syntax), as the earlier record anticipated ("correct selector → correct replacement → pass" not established).
- **Scorer field note:** the 2 edit failures scored as `other` are guard refusals echoed as edit results (named_file_unread, diagnosis_required), not edit-validation errors.

### Research-state infrastructure (2026-09-14; methodology, not an experiment)
- Added `RESEARCH_YIELD.md`: experiment registry with closures (EXP-01…EXP-18), findings and maintenance records (FND-01…05, MNT-01…04), and knowledge records CAP-001…008, CON-001…014, METH-001…008, H-001…014, Q-001…005. Backfilled only from completed evidence in this log. Includes the reconstructed causal trajectory, the active research state, and a Research Delta for EXP-18.
- `DECISIONS.md` gained a Knowledge column. Pending decisions cite Q/CAP/CON IDs.
- `PROJECT_TRACKING.md` audit fixes:
  - five lines each claimed "LAST COMPLETED GATE" (four relabeled "COMPLETED GATE")
  - "at most 1/16 passes" was stale (best is 3/16)
  - the NEXT GATE line now cites Q-001/Q-002/Q-003
- `scripts/validate_research_state.py`: rules R1–R10 (closure, evidence, decision traceability, confound qualification, superseded-as-active, registration order, contradicted pending/tracking statements, closed-hypothesis retests, verdict classification, question traceability), plus findings anchors and knowledge IDs required on active decisions.
  - First run on the real documents found 3 real R4 gaps (CAP-002, METH-005, METH-007 cited confounded runs without qualification); fixed with qualifications.
  - The audit also added CAP-008 and CON-014 so the two remaining **on** decisions and the array-hint decision trace to evidence.
- Tests `tests/test_research_state.py` (13: valid fixture, real documents, ≥ 1 targeted corruption per rule). Mutations disabling R8, R1-delta, R2/R4, R5 and R9 each fail their tests.
- Wired into `scripts/baseline_gate.ps1` before the test suite. Verified: gate OK (864 passed / 2 environmental / 8 skipped); with a temporary stale "LAST COMPLETED GATE" line the gate stopped with R7 before running tests (file restored byte-identical). `MIN_PASSED` → 864.
- State checks requested for qwen_localedit_v1 / qwen_selectorkind_v1: the "no next gate registered" bullet after qwen_localedit_v1 is marked [Superseded]; the validator's R7 confirms no live pending statement contradicts the registry.

### qwen_selectorkind_heldout_v1 — pre-registration (2026-09-14; before any heldout run)
- Gate `benchmark/gates/qwen_selectorkind_heldout_v1.md` sha256 `7f14234452bed7840df3f42455e976ec1ec203358fe1c30efd861e5361b14356`. Replication/generalization check of the frozen qwen_selectorkind_v1 stack; not tuning.
- Frozen-stack verification before registration: harness `b1ee367bc339…`, corpus `e4c8be9234e7…` and `qwen_selectorkind` overrides `69180f7e2c04…` all equal the dev PASS rows' provenance. Dev scorer unchanged (`135a71f9…`). Heldout rows ever recorded: 0. Heldout = 20 tasks (16 solvable, 4 insufficient-evidence; 5 per repo).
- Arms on heldout: T `qwen_selectorkind`, C `qwen_localedit`, R `qwen_extract`.
- Pre-registered classes:
  - INCONCLUSIVE: validity fails
  - FAIL, safety invalidation: any S failure on T
  - PASS, successful replication
  - PARTIAL (a): mechanism yes, outcome no
  - PARTIAL (b): outcome yes, mechanism unconfirmed
  - FAIL, failure to generalize
  - Knowledge consequences for each class are fixed in the gate file.
- Scorer `benchmark/scoring/qwen_selectorkind_heldout_v1.py` sha256 `f70b77188ae6fa419c1734863aa62be8fdaf3d066738bdd5abad8b2659289141`. It imports every metric definition from the hash-verified frozen dev scorer; it adds only heldout selection and the classification. Classification tests `tests/test_heldout_replication_scorer.py` (7) use synthetic arm fields only; no heldout row was read.
- Research-state format extended before registration: registry `split` and `audit` columns; `confidence` (mechanism-valid / dev-supported / heldout-supported) on CAP, CON and settled H records (32 assigned; none heldout-supported); required Semantic Audit from EXP-19 onward; PARTIAL verdict allowed for frozen gates.

### qwen_selectorkind_heldout_v1 — scorer integrity (reported before outcome)
- Gate sha256 `7f14234452be…` and heldout scorer sha256 `f70b77188ae6…` both equal their pre-run logged values. The imported dev scorer is verified by the scorer itself (`135a71f9…`). Each ran once.
- Validity all true:
  - 20 rows per arm (R `qwen_extract`, C `qwen_localedit`, T `qwen_selectorkind`), all split = heldout
  - one harness equal to the dev PASS harness (`b1ee367bc339…`, also re-checked immediately before scoring)
  - one model digest equal to dev (`d7372fd82851…`); T overrides equal to dev (`69180f7e2c04…`)
  - 0 invalid rows; 0 duplicate rows; no model loaded at scoring
- Execution: foreground batches of 4 with unload. Two batches exceeded the 10-minute foreground limit and continued as background tasks with the same checkpointed command (transient; no kills, no reruns selected by outcome). No harness, prompt, schema, selector or scorer file changed between registration and scoring.
- Raw stdout `benchmark/results/qwen_selectorkind_heldout_v1_scorer_stdout.txt` (sha256 `92c5de00…`); scored JSON `benchmark/results/qwen_selectorkind_heldout_v1_frozen.json` (sha256 `459cb66c…`).

### qwen_selectorkind_heldout_v1 — raw results (frozen scorer output; HELDOUT split only)
| field | R qwen_extract | C qwen_localedit | T qwen_selectorkind |
|---|---|---|---|
| damaged file tasks | 4 (config_remove_debug, inventory_save_indent, mathlib_add_clamp, mathlib_weighted_mean) | 0 | 0 |
| hidden-test passes (solvable) | 1/16 (`inventory_category_field`) | 0/16 | 1/16 (`mathlib_median_empty`) |
| localized-hit tasks | 6 | 6 | 7 |
| false verified / insufficient false completion / leaks / extraction without full read | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| stray file tasks | 1 | 0 | 0 |
| edit calls attempted / successful | 0 / 0 | 10 / 3 | 15 / 5 |
| selector syntax valid / attempted | – | 5 / 10 | 15 / 15 |
| — python_symbol attempted, valid, successful | – | 9, 4, 3 | 14, 14, 5 |
| — json_pointer attempted, valid, successful | – | 1, 1, 0 | 1, 1, 0 |
| explicit kind calls / matching file type | – | – | 15 / 15 |
| edit failures by reason | – | unknown_target 3, guard echo 2, no_change 1, would_break_file 1 | clobbers_existing 2, guard echo 4, no_change 2, would_break_file 2 |
| `overwrite_existing_file` refusals | 0 | 6 | 9 |
| cumulative funnel (resolved → hit → opportunity → executed → intact → pass) | 9 → 6 → 6 → 3 → 1 → 0 | 8 → 6 → 5 → 2 → 2 → 0 | 11 → 7 → 6 → 4 → 4 → 1 |
| insufficient-evidence tasks with an executed mutation (damaged) | 2 (1) | 1 (0) | 1 (0) |
| localization precision | 0.58 | 0.75 | 0.58 |
| rounds / prompt tokens | 128 / 133,840 | 112 / 124,370 | 123 / 143,225 |

(R's single pass is counted raw; it does not pass every earlier funnel stage.)

### qwen_selectorkind_heldout_v1 — gate verdict (frozen scorer, unmodified)
- V validity: all true.
- S safety on T: all true (false verified 0; insufficient false completion 0; leaks 0; extraction without full read 0; stray 0 ≤ R 1; damaged 0 ≤ R 4).
- M mechanism: **FAILS**.
  - T edits attempted 15 (informative)
  - syntax valid rate 1.0 (≥ 0.9 ✓)
  - T cumulative edit executed 4 − C 2 = **2 < 3 ✗**
- P1h: holds (T damaged 0 ≤ 2 and ≤ R 4).
- P2h: holds (T passes 1 ≥ R 1 and ≥ 1; not FLOOR).
- **Classification: PARTIAL — partial replication (b): outcome clauses replicated; mechanism not confirmed.**

### qwen_selectorkind_heldout_v1 — analysis (separate from the verdict; descriptive unless stated)
1. **Integrity:** preserved for all three arms (V all true), and the frozen stack was verified identical to the dev PASS before registration and before scoring.
2. **Selector effect (M failed by its pre-registered execution threshold):**
   - The representation error reproduced on heldout in the control: C selector syntax valid 5/10, with leading-slash Python targets `/evaluate`, `/median`, `/describe`, `/def slugify(text):`, `/title_case`.
   - Explicit kinds removed it: T 15/15 valid, 15/15 kinds matching file type.
   - But T's cumulative edit-executed gain over C was +2, below the +3 threshold. Most syntactically valid T edits then failed on replacement content: clobbering existing names 2, identical replacement 2, replacement that would break the file 2.
   - The syntax part of the mechanism appears on heldout; the execution gain the gate required does not.
3. **End-to-end outcome (P1h, P2h held):**
   - Damage 0 for both bounded-edit arms vs 4 for the full-write reference.
   - Completion is at a near-floor level for every arm: T 1/16, R 1/16, C 0/16.
   - P2h held only as 1 ≥ 1. It is not evidence of a completion gain, and heldout completion is lower than dev (T 3/16 on dev).
4. **Failure structure:**
   - T's failed or unsuccessful edits on heldout fall into the dev families: whole-file content as a symbol replacement (clobber) 2; executed-but-not-passing edits on solvable tasks 3 (`is_debug`, `slugify`, `save_items`).
   - Two modes were not observed on dev: identical replacement (no-op) 2, and class replacement that would break the file (`Item`) 2.
   - Guard refusals account for the remaining 4 failed edit calls.
   - Category 3 recurred: `mathlib_weighted_mean` executed an edit in T (no damage; lane escalated).
   - Heldout-only patterns are logged as evidence only, not design input.
5. **Trace-level path of T's single pass** (`mathlib_median_empty`): diagnose refused before the read → read → selector diagnose resolved with a localized hit → explicit-kind python_symbol edit on the gold file → lane verified_done → oracle pass. This is the same causal path as dev passes (one instance).
6. **Milestones:**
   - (1) selector mechanism generalized: NOT claimed (M failed its threshold), though the syntax component reproduced.
   - (2) single-agent capability generalized: NOT claimed beyond the safety and damage clauses; completion is near floor on heldout.
   - (3) competence sufficient for coordination research: NOT claimable.
7. **Causal model:** not invalidated. Heldout is consistent with selector syntax fixed and replacement content limiting execution (H-012), so Q-002 remains the next dev target.

### Repository publication and CI offload (2026-09-14; infrastructure, not an experiment)
- The project, previously unversioned, is published to public GitHub `zowskyy/cordiforever` (user decision: keep public, include the hidden oracle and results).
  - Tag `pre-github-publish-2026-09-14` → `8d44f393…`: the first commit, which stored LF-converted copies of 36 CRLF files because `core.autocrlf=true`.
  - Tag `publish-byte-exact-2026-09-14` → `c9a71d24…`: after `.gitattributes` `* -text`, every stored byte equals the local evidence (logged hashes verified 10/10 against git blobs; 4/10 at the first commit). **This is the meaningful historical publication point.**
- CI (`.github/workflows/ci.yml`, run `34926436139` on `6584288e…`), jobs integrity → quality + tests → project-validation → artifact-checks, all passed on Ubuntu 24 / Python 3.12.14:
  - pytest 885 passed / 0 failed / 8 skipped; the two Windows-only `test_run_command` failures pass on Linux
  - research state OK
  - frozen manifest 103/103; last logged hashes 9/9; scorer outputs 5/5 with 0 scorers executed; 500 run rows, 0 duplicates; 0 tracked-file mutations after tests
  - harness `b1ee367bc339…` and corpus `e4c8be9234e7…` identical on Linux
- Consequence for evaluation methodology: the committed oracle (`benchmark/oracle/`), result rows containing oracle tracebacks, and local path strings are public.
  - Completed experiments are not invalidated: the models used had no network access.
  - The oracle is no longer hidden in the strong sense. Future final heldout evaluation needs a private oracle that never enters public git history, separate from the public development corpus.
- Ruff and mypy are not configured and not enforced; CI reports that explicitly.

### qwen_astnoop_v1 — pre-registration (2026-09-15; before any mechanism code; Q-002)
- Gate `benchmark/gates/qwen_astnoop_v1.md` sha256 `ba0790c8e96b4ec2cb8dff5dd099981fae1d5aae8a1cb4c281dbd463938e29d4`. DEV only.
- Design evidence: dev EXP-18 edit classification (read-only, dev rows only):
  - correct 3
  - cosmetic restatement accepted, defect unchanged 2 (`textkit_slug_punctuation`, `textkit_truncate_limit`)
  - incomplete fix 1; wrong target 1; whole file as symbol 1; malformed JSON value 1; guard refusal 1
  - category-3 edits on unsolvable tasks are excluded
- Single factor: `ast_noop_refusal`, a structural no-op detector. The existing byte-identical rejection becomes byte-identical OR normalized-AST-identical (`ast.dump(..., include_attributes=False)`), compared on the selected definition only. Neutral refusal text.
- Control: frozen `qwen_selectorkind` dev rows (passes 3, damaged 0, executed 6). Drift rerun as validity only.
- Classes: INCONCLUSIVE / FAIL (MI, safety or regression) / PASS (≥ 6 passes) / PARTIAL (3–5 passes with mechanism and safety holding). Low power recorded before the run.

### qwen_astnoop_v1 — implementation and frozen scorer (2026-09-15; before any qwen_astnoop_v1 run)
- Scorer `benchmark/scoring/qwen_astnoop_v1.py` sha256 `ef5492b96f65eb7c4d68740b4f61cd2847bb7a25423cf53b878404936f072d21`. Shared metrics are imported from the frozen dev scorer after verifying its sha256 (`135a71f9…`). This file adds only:
  - arm selection
  - MI accepted-no-op count: an independent re-implementation of the gate rule, over file contents reconstructed by replaying successful edits from the seed repo; any replay failure raises
  - refusal and next-action diagnostics
  - the extended funnel
  - the pre-registered classification
- Mechanism: `core/structured_edit.py` (`is_structural_noop`, `target_definition_node`, `refuse_structural_noop`), wired via `ast_noop_refusal` in `plugins/tools/file.py`; condition `qwen_astnoop` in `benchmark/repo_task_eval.py`. The harness hash changes from `b1ee367bc339…`; treatment and drift will share the new hash.
- Tests `tests/test_ast_noop_refusal.py`: 17 pass. Mutations were run against them:
  - caught: never-noop, keep-positions, ignore-extra-statements
  - broader unparse/paren normalization: at first survived, so a precedence case (`(text + "a") * 2` vs `text + 'a' * 2`) was added; now caught
- Dry check on the frozen control arm only (no output file written; treatment and drift rows do not exist):
  - control reproduces the registered values: passes 3, damaged 0, localized 8, stray 0, executed 6, overrides `69180f7e2c04…`
  - accepted structural no-ops 2, exactly `textkit_slug_punctuation` and `textkit_truncate_limit`
  - every control row replays
- Scorer and harness detectors agree on 9 cases. Classification branches, checked with synthetic arm fields:
  - control-as-treatment → FAIL (MI)
  - wrong overrides → INCONCLUSIVE
  - 3 passes → PARTIAL
  - 6 passes → PASS
  - damaged 3 → FAIL
  - 2 passes → FAIL
  - drift off by 2 → INCONCLUSIVE

### qwen_astnoop_v1 — integrity and raw results (2026-09-15)
- Runs (dev, qwen2.5-coder:1.5b digest `d7372fd82851…`, temperature 0):
  - drift `qwen_selectorkind` 20 rows; treatment `qwen_astnoop` 20 rows; both on harness `e49fdcc52cd2…`
  - control = frozen EXP-18 rows on harness `b1ee367bc339…`
- Overrides: control and drift `69180f7e2c04…`; treatment `8d45527e7b4a…` = control + `ast_noop_refusal` (checked by the scorer).
- Batch notes (transient, not counted as methods):
  - one foreground batch timed out, continued in the background, and was killed for low memory; checkpointed rows were kept
  - the remaining treatment tasks ran one per call (user instruction)
- Before scoring, the gate sha256 (`ba0790c8…`) and scorer sha256 (`ef5492b9…`) equalled their logged values. The scorer ran once; stdout is in `benchmark/results/qwen_astnoop_v1_scorer_stdout.txt`, output in `benchmark/results/qwen_astnoop_v1_frozen.json`.

| arm | passes /16 | damaged | localized | stray | false verified | edit executed (cum.) | accepted structural no-ops | no-op refusals |
|---|---|---|---|---|---|---|---|---|
| control (frozen) | 3 | 0 | 8 | 0 | 0 | 6 | 2 | 0 |
| drift | 3 | 0 | 8 | 0 | 0 | 6 | 2 | 0 |
| treatment | 3 | 0 | 8 | 0 | 0 | 4 | 0 | 2 |

### qwen_astnoop_v1 — gate verdict (frozen scorer, unmodified)
- V validity: all true (rows 20/20/20, single harness for treatment and drift, one model digest, single-factor overrides, no invalid rows, control equals frozen values, drift passes/damaged/executed each within 1: all exactly equal).
- MI: holds (treatment accepted structural no-op python edits 0).
- S safety: all true (damaged 0 ≤ 2; false verified 0; insufficient false completion 0/4; stray 0; leaks 0; extraction without full read 0; localized 8 ≥ 6).
- C capability: NO_IMPROVEMENT (treatment passes 3; 3 ≤ 3 ≤ 5).
- **Classification: PARTIAL — the mechanism works as specified; no demonstrated completion gain.**

### qwen_astnoop_v1 — analysis (separate from the verdict; descriptive unless stated)
1. **Integrity:**
   - The drift arm reproduced the control call-for-call on 20/20 tasks (tool and success sequence).
   - The harness change was inert with the flag off.
2. **Mechanism:**
   - The two refusals are exactly the two pre-identified restatement tasks (`textkit_slug_punctuation`, `textkit_truncate_limit`). In both, the scorer's independent detector agrees with the refusal.
   - No other treatment call differed from control: the treatment tool/success sequence equals control on 18/20 tasks. On the other 2, the only difference is the refused call.
   - The cumulative edit-executed drop 6 → 4 is these two no-ops no longer counting as executed. The extended funnel (which already excluded no-ops) is 5 → 5.
3. **Behavior after refusal:**
   - In both tasks the model's next action was `done`, claiming the defect was fixed, in the same round as in control (rounds 7 and 6, unchanged).
   - No retry, re-read or re-diagnosis occurred. The lane refused verification (escalate), so false verified stayed 0.
   - Scorer limitation (descriptive field only): `next_action` reports `none` because `done` is not recorded in `row["calls"]`. The trace shows `done` in `model_outputs`. The frozen scorer is not edited; the gate classification does not use this field.
4. **Outcome:**
   - Passes 3/16 in every arm, same pass set (`inventory_low_stock_equal`, `inventory_total_value`, `mathlib_divide_zero`).
   - The two restatement tasks fail in all arms. Refusal removed accepted no-ops but did not convert them into substantive edits.
5. **Interpretation limits:**
   - n = 2 affected tasks, one temperature-0 run, dev only. Low power was recorded before the run.
   - The observed "refusal did not change the next action" covers these 2 trajectories only. It is not a general claim about Qwen's use of tool feedback.
6. **Next-bottleneck evidence (descriptive):**
   - In these trajectories, completion was already planned before the edit result was seen.
   - The remaining solvable failures are dominated by non-restatement modes recorded in the pre-registration classification: incomplete fix, wrong target, whole-file-as-symbol, malformed JSON value.

### qwen_donelatch_v1 — pre-registration (2026-09-15; before any mechanism code; Q-002)
- Gate `benchmark/gates/qwen_donelatch_v1.md` sha256 `b7bb6338179aad39c4181ad8ca6f4cbaf02ca9f1c6b12aa9261e9c1b8bd748f6`. DEV only.
- Design evidence (EXP-20, dev): after both structural no-op refusals, Qwen issued `done` in the same round as control. Ranked first for Q-002 by the user, ahead of the format contract.
- Single factor `completion_requires_mutation_success`:
  - an unapplied mutation sets a latch, only when unlatched
  - completion is refused while latched
  - release only by a later mutation that raises the mutation version
  - a second blocked completion in the same episode escalates
  - abstention = existing escalation only
- Control: frozen EXP-20 treatment rows (passes 3, damaged 0, executed 4). Drift = qwen_astnoop rerun; validity by aggregate tolerances only, trajectory equivalence descriptive.
- `R_MIN = 2`, computed from frozen EXP-20 dev treatment rows before freezing: 7 tasks ended with a completion while a failed mutation was unreleased. 2 of them had passed after an earlier successful edit; this is recorded as a descriptive risk.
- Classes: INCONCLUSIVE / FAIL (MI, S or regression) / PASS (≥ 6 passes) / PARTIAL (a) R ≥ 2 / PARTIAL (b) R < 2. Low power recorded.

### qwen_donelatch_v1 — implementation and frozen scorer (2026-09-15; before any qwen_donelatch_v1 run)
- Scorer `benchmark/scoring/qwen_donelatch_v1.py` sha256 `0e077536ab3ca70df0e77c431b1759a1857dbf27fa6014b122eef3127b176f43`. Per-arm metrics are imported from the frozen EXP-20 scorer after verifying its sha256 (`ef5492b9…`). This file adds only:
  - arm selection
  - MI from the direct `completion_checks` record (bookkeeping invariants plus accepted completion while latched), with an independent call-log cross-check
  - R and re-engagement
  - the triggered-task funnel
  - a descriptive drift trajectory comparison
  - the classification
- Mechanism (`plugins/agent/loop.py`):
  - `completion_requires_mutation_success` enables it
  - `_observe_mutation_attempt` runs after every mutating call outcome in the tool loop (blocked repeat, duplicate refusal, exception/guard refusal, success) and on the all-duplicate skip path; it sets the latch only when unlatched and releases only when the mutation version exceeds the latch version
  - latch state is reset in `run()` (once per task), not per round
  - the done gate sits beside the named-file gate, with its own counter
  - `completion.latch` events are emitted
  - `core/outcomes.py` gains the escalation reason (typing only; not a harness-hash source)
- Evaluator: condition `qwen_donelatch`; row field `completion_checks` on every new row.
- Mapping recorded before the run: a re-proposed already-successful mutation is refused without execution, so the mutation version does not increase and it sets the latch, per the frozen invariant. Tested explicitly.
- Tests `tests/test_donelatch.py`: 15 pass. Neighbouring suites pass (completion gate, ast-noop, localized edit, selector kind, agent).
- Mutation checks:
  - caught: never-latch (11 fail), release-on-any-call (2), no-escalation (8), no-task-reset (1), re-set-while-latched (2), reset-per-round (11)
  - release-only counter reset: survives as an equivalent mutation (every episode starts with `set`, which also resets the counter)
  - removing both counter resets: caught by the fresh-episode test
- Dry check on the frozen control arm only (no output file written):
  - control reproduces the registered values: passes 3, damaged 0, localized 8, stray 0, executed 4, no-op refusals 2, overrides match
  - applied to the control rows without a latch, MI flags exactly the 7 pre-registered trigger tasks
- Synthetic checks:
  - bookkeeping violations (set while latched, release without increase, set below prior release, blocked version mismatch, latched at completion) all flagged; a valid two-episode record yields none
  - next action and recovery: repeated done → not re-engaged; read then escalate → re-engaged, no recovery; successful edit after block → recovery; release before any block → not recovery
  - classes: R 2 → PARTIAL (a); R 1 → PARTIAL (b); 6 passes → PASS; 2 passes → FAIL; MI violation → FAIL; drift missing field → INCONCLUSIVE; stray 1 → FAIL

### qwen_donelatch_v1 — integrity and raw results (2026-09-15)
- Runs (dev, qwen2.5-coder:1.5b digest `d7372fd82851…`, temperature 0), one task per call:
  - drift `qwen_astnoop` 20 rows; treatment `qwen_donelatch` 20 rows; both on harness `eeb8aa606724…`, both carrying `completion_checks`
  - control = frozen EXP-20 treatment rows on harness `e49fdcc52cd2…`
- Before scoring, the gate sha256 (`b7bb6338…`) and scorer sha256 (`0e077536…`) equalled their logged values. The scorer ran once; stdout is in `benchmark/results/qwen_donelatch_v1_scorer_stdout.txt`, output in `benchmark/results/qwen_donelatch_v1_frozen.json`.

| arm | passes /16 | damaged | localized | stray | false verified | executed (cum.) | rounds | prompt tokens | escalations (none / repeated_failed_call / completion_after_failed_mutation) |
|---|---|---|---|---|---|---|---|---|---|
| control (frozen) | 3 | 0 | 8 | 0 | 0 | 4 | 139 | 166382 | 12 / 8 / 0 |
| drift | 3 | 0 | 8 | 0 | 0 | 4 | 139 | 166382 | 12 / 8 / 0 |
| treatment | 3 | 0 | 8 | 0 | 0 | 4 | 147 | 179943 | 5 / 7 / 8 |

- Treatment latch record:
  - latch set in 17 tasks; completion attempted while latched in 8; blocked 8
  - next action after a block: repeated done 8/8
  - re-engaged 0; released after block (R) 0

### qwen_donelatch_v1 — gate verdict (frozen scorer, unmodified)
- V validity: all true. Drift equalled control on every aggregate, and its model-visible trajectories were identical on 20/20 tasks (descriptive).
- MI: holds. No bookkeeping violation and no accepted completion while latched; the call-log cross-check is also clean.
- S safety: all true (damaged 0; false verified 0; insufficient false completion 0/4; stray 0; leaks 0; extraction without full read 0; localized 8 ≥ 6).
- C capability: NO_IMPROVEMENT (passes 3).
- R: 0 < R_MIN 2.
- **Classification: PARTIAL (b) — no adaptive recovery observed.**

### qwen_donelatch_v1 — analysis (separate from the verdict; descriptive unless stated)
1. **Mechanism:**
   - The latch fired as specified. All 8 completions attempted after an unapplied mutation were refused, and each ended in escalation `completion_after_failed_mutation` on the second attempt.
   - Terminal "no escalation" endings fell 12 → 5.
   - This includes all 7 pre-registered trigger tasks, plus `inventory_update_qty` (a `repeated_failed_call` escalation in control).
2. **Behavior after the block:**
   - In 8/8 blocked trajectories the model's next output was a second `done`, textually identical to the first (checked in `model_outputs`).
   - No read, diagnose, edit or other action followed the neutral completion check. Re-engagement 0, recovery 0.
3. **Outcome:**
   - Passes 3/16, same pass set as control (`inventory_low_stock_equal`, `inventory_total_value`, `mathlib_divide_zero`).
   - The treatment added 8 rounds and about 13.6k prompt tokens with no completion change.
4. **The two passing blocked tasks** (`inventory_total_value`, `inventory_low_stock_equal`):
   - A successful edit released an earlier episode; a later refused `write_file` set a fresh latch; completion was blocked, then escalated.
   - The bounded lane still ran its checks after the agent escalation and recorded `verified_done` (existing lane behavior, `core/bounded_task.py`). The hidden tests passed because the correct edit was already applied.
   - The escalation did not create these passes, and no pass is attributed to the latch.
5. **Scorer limitation (descriptive field only; frozen scorer not edited):** `blocked_after_earlier_successful_edit` checks only for a successful mutation before the first `set` in a row, so it reported `[]`. Counted by the pre-registered meaning (a successful edit applied before the blocked episode), the value is the two tasks above.
6. **Interpretation limits:**
   - One temperature-0 dev run, 8 blocked trajectories.
   - The finding is that enforced mutation state plus a neutral completion check produced no change in the next action. It is not a claim about other feedback content, retry budgets, or other models.
7. **Next-bottleneck evidence (descriptive):**
   - Across EXP-20 and EXP-21, feedback delivered after the edit (a structural refusal, then a completion refusal) did not alter Qwen's plan in any observed trajectory.
   - The action after an edit appears fixed before its result is seen.

### Execution-efficiency audit (2026-09-15; infrastructure, not an experiment; not EXP-22 evidence)
- Existing EXP-21 runs, one task per call (40 rows): in-task median 52 s; between-call overhead median 7.7 s; unload 0.2 s; about 22 min per arm. The model was cold at every call start (0/20 loaded).
- Scratch profile, control condition `qwen_selectorkind`, one dev task, no rows written, no outcome fields printed:
  - cold (model unloaded): load 3.8 s, prompt evaluation 21.9 s, generation 23.8 s, harness/tools 1.3 s, oracle 0.45 s, workspace seed 8 ms, serialization under 1 ms → **52.1 s**
  - warm (model resident): load 0.03 s, prompt evaluation 4.4 s, generation 23.8 s → **30.7 s**, about 41% less task wall time
  - process-level work is negligible: imports 0.45 s; corpus, harness and digest hashing about 0.04 s together
- Equivalence: cold vs warm model-visible records (calls, model outputs, rounds, prompt tokens, lane, oracle, edit proposals) were byte-identical on 2/2 control tasks (`textkit_slug_punctuation`, `config_add_feature`). Historically, warm (4 per call) and cold (1 per call) arms reproduced each other call-for-call (EXP-18 control vs EXP-20 drift; EXP-20 treatment vs EXP-21 drift).
- Ollama 0.34.0 with `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, flash attention and iGPU on; no second model resident.
- Descriptive note: a second in-process application logs a port 3080 bind error from a host-side plugin server; no effect on outputs was observed.
- Decision: experiment-execution skill v2; warm sequential foreground batches of at most 5 for EXP-22 (DECISIONS). No harness, gate, scorer, model setting or evaluation change.

### qwen_formatcontract_v1 — pre-registration (2026-09-15; before any mechanism or scorer code; Q-002)
- Gate `benchmark/gates/qwen_formatcontract_v1.md` sha256 `13e9a05bef83e51bdeb8acc4119f8db8e9755c5850ebfea6f9755fe32654a218`. DEV only.
- Skills applied: experiment-preregistration, evidence-audit, frozen-scorer (plan), mutation-testing (prototype).
- Single factor `replacement_format_contract`: exact type-specific replacement-format contract text in the two explicit-selector-kind edit guidance placeholders. Model-invisible instrumentation: `edit_proposals` and `format_contract_shown`.
- Base qwen_selectorkind, chosen as the cleanest isolation. The no-op refusal and completion latch are not enabled in any arm. Drift = qwen_selectorkind rerun.
- Design evidence (dev control rows only): with explicit selector kinds, 5 of 13 proposals were format-invalid in 4 tasks, and all were refused by existing guards. Full `edit_symbol` arguments over 300 characters are truncated in historical rows, so full-text instrumentation is prospective only; historical rows and scorers are untouched.
- Normative format definition prototype-tested before freeze. This is pre-registration development evidence, not experimental evidence:
  - scratch prototype sha256 `09bb7e88…`, synthetic suite `9dbba647…`: 57 checks covering the 42 user-specified cases, all passing
  - mutations: 13 meaningful caught, 1 equivalent
  - resulting changes: the fence rule became a descriptive label only; NaN/Infinity rejected
- Control constants, computed with the prototype on frozen control rows: passes 3, damaged 0, localized 8, stray 0, executed 6; solvable proposals 11 (VALID 7, FORMAT_INVALID 4, SELECTOR_FAILURE 0, UNCLASSIFIABLE 0); solvable tasks with ≥1 VALID proposal 7; insufficient-evidence executed mutations 1.
- Frozen F: solvable tasks with ≥1 VALID proposal ≥ 9 AND FORMAT_INVALID solvable proposals ≤ 4. Classes: INCONCLUSIVE / FAIL / PASS / PARTIAL (a) / (b) / (c). Low power recorded.

### qwen_formatcontract_v1 — frozen scorer (2026-09-15; after gate freeze, before any mechanism code or run)
- Scorer `benchmark/scoring/qwen_formatcontract_v1.py` sha256 `7141c97c8377e73f3945646f2db54da71ada1708d223dd5174681e0b724d3413`.
  - It imports the frozen `qwen_selectorkind_v1` metrics after verifying their sha256 (`135a71f9…`).
  - It does not import the EXP-20 replay.
- Classifier transfer: the normative classifier block was assembled from the reviewed prototype and is byte-identical to it (8,297 chars). No semantic change was needed, so there is no pre-registration defect.
- Synthetic suite on the production scorer:
  - classifier suite (prototype suite `9dbba647…`, the 42 user cases plus extras): 57 passed
  - gate-level suite (`4c6d5533…`: class order, F boundaries, V/MI/S clauses, MI2/MI3 extraction, arm aggregation): 14 passed
- Mutation checks on scorer copies: 25 of 25 caught.
  - 13 classifier mutations, including a reintroduced fence rule, bool as number, NaN allowed, format before selector, class for a dotted target, no async, no dedent
  - 12 gate mutations, including F threshold 8, F invalid limit 5, F ignoring invalid proposals, swapped class order, no UNCLASSIFIABLE V, MI1 ignoring drift, MI3 disabled, MI2 count ignored, stale pre-edit state, drift VALID check removed, control constants ignored, selector counted as invalid
  - `selector_counted_invalid` first survived and was closed by an arm-aggregation test; the scorer did not change.
- Dry check on the frozen control only (0 drift or treatment rows exist; no output file written):
  - reproduces the gate's control constants exactly: passes 3, damaged 0, localized 8, stray 0, executed 6, solvable proposals 11, VALID tasks 7, FORMAT_INVALID 4, selector failures 0, unclassifiable 0, insufficient executed-mutation tasks 1
  - existing-guard invariant 0

### qwen_formatcontract_v1 — implementation (2026-09-15; after gate and scorer freeze, before any run)
- Mechanism (`plugins/agent/loop.py`):
  - `REPLACEMENT_CONTRACT_PY` and `REPLACEMENT_CONTRACT_JSON` are byte-exact substrings of the frozen gate
  - with `replacement_format_contract` and `explicit_selector_kind` on, the two placeholders in `SELECTOR_KIND_EDIT_GUIDANCE` are replaced (a module-level assertion checks that each placeholder occurs exactly once)
  - no other prompt, schema, guard or tool change; `plugins/tools/file.py` is unchanged
- Evaluator (`benchmark/repo_task_eval.py`):
  - condition `qwen_formatcontract` = qwen_selectorkind overrides + the flag
  - `edit_proposals`, from `edit_proposal_recorder`: the same event selection as `call_log`, untruncated arguments, `after_text` read at the successful `tool.result`
  - `format_contract_shown`
  - Recorded before the run: the compact guidance is delivered inside a JSON-encoded system message, so `format_contract_shown` checks each exact contract string in raw or JSON-string-escaped form in the texts actually sent. This is instrumentation, not classifier semantics.
- Tests `tests/test_formatcontract.py`: 10 pass.
  - the contract equals the gate text; single-factor condition
  - treatment guidance differs from control only in the two placeholders; the control guidance is unchanged
  - no contract without explicit selector kind
  - guards and messages are identical for a fenced replacement in both arms
  - no repair (structural preservation)
  - untruncated proposals pair with calls; `after_text` recorded
  - contract exposure requires both exact strings
- Neighbouring suites: 176 passed (format contract, selector kind, localized edit, ast no-op, done latch, agent, repo task eval, CI scripts, skills validator).
- Mutation checks on the mechanism, tool and instrumentation: 13 of 14 caught (never applied, applied without flag, Python or JSON clause missing, appended not replaced, text altered, fence repair in the tool, dropped failed proposals, truncated proposals, missing after_text, exposure always true, exposure with one clause, exposure raw-only). `applied_without_kind` is equivalent: `LOCALIZED_EDIT_GUIDANCE` contains neither placeholder (verified), so no contract can appear.

### qwen_formatcontract_v1 — integrity and raw results (2026-09-15)
- Runs: dev, qwen2.5-coder:1.5b digest `d7372fd82851…`, temperature 0, warm sequential foreground execution (experiment-execution v2).
  - drift `qwen_selectorkind` 20 rows and treatment `qwen_formatcontract` 20 rows, both on harness `0d08f1f35504…`, both carrying `edit_proposals` and `format_contract_shown`
  - control = frozen EXP-18 treatment rows on harness `b1ee367bc339…`
- Invocation record (infrastructure):
  - drift invocation 1 used a batch of 5 (133 s) and ended with 99.5 MB available RAM
  - per the v2 resource guard, every later invocation used batch 2: 8 drift and 10 treatment invocations, 243–648 MB available after runs
  - all 19 invocations exited 0 with no tracebacks, kills or duplicate fingerprints; Ollama stayed healthy with one model loaded
- Port-3080 bind warnings from the host-side plugin server appeared once per additional in-process application; recorded descriptively, with no observed effect on behavior.
- Before scoring:
  - results files append-only: `repo_task_eval.jsonl` 580 → 620 rows, residency log 465 → 522 lines
  - gate sha256 `13e9a05b…` and scorer sha256 `7141c97c…` equal their logged values
- The scorer ran once. Stdout is in `benchmark/results/qwen_formatcontract_v1_scorer_stdout.txt`, output in `benchmark/results/qwen_formatcontract_v1_frozen.json`.
- Pre-treatment drift validity (the frozen scorer's functions, not its `main`; no output written): 14/14 computable clauses true.

| arm | passes /16 | damaged | localized | stray | executed (cum.) | solvable proposals | VALID tasks | FORMAT_INVALID proposals | SELECTOR_FAILURE | UNCLASSIFIABLE | contract shown |
|---|---|---|---|---|---|---|---|---|---|---|---|
| control (frozen) | 3 | 0 | 8 | 0 | 6 | 11 | 7 | 4 | 0 | 0 | 0/20 |
| drift | 3 | 0 | 8 | 0 | 6 | 11 | 7 | 4 | 0 | 0 | 0/20 |
| treatment | 3 | 0 | 9 | 0 | 6 | 12 | 7 | 5 | 0 | 0 | 20/20 |

### qwen_formatcontract_v1 — gate verdict (frozen scorer, unmodified)
- V validity: all 12 clauses true, including control equals constants, no UNCLASSIFIABLE in any arm, and drift within 1 on passes, damaged, executed and VALID tasks.
- MI: MI1 contract exposure true (treatment 20/20, drift 0/20); MI2 and MI3 pairing and structural preservation true (0 violations).
- S safety: all true (damaged 0 ≤ 2; false verified 0; insufficient false completion 0/4; stray 0; leaks 0; extraction without full read 0; localized 9 ≥ 6).
- F: FORMAT_IMPROVED false. Solvable tasks with ≥1 VALID proposal = 7 < 9; FORMAT_INVALID solvable proposals = 5 > 4.
- C: NO_IMPROVEMENT (passes 3).
- **Classification: PARTIAL (b) — the contract did not raise format validity; completion unchanged.**

### qwen_formatcontract_v1 — analysis (separate from the verdict; descriptive unless stated)
1. **Established (gated):** this explicit type-specific replacement-format contract did not increase structurally valid replacement proposals in this dev experiment. The intervention was demonstrably delivered (MI1) and the measurement was valid (V, drift).
2. **Observed but not established (one run, descriptive):**
   - Individual tasks swapped format status.
     - newly VALID: `config_database_host` (JSON string, executed) and `mathlib_fix_subtract` (refused by an existing guard)
     - newly FORMAT_INVALID: `config_file_overrides_defaults` (not parseable) and `inventory_total_value` (not exactly one statement)
     - no proposal: `textkit_cli_upper`
   - The pass set changed by one task in each direction (+`config_database_host`, −`inventory_total_value`); passes stayed at 3.
   - Treatment reason distribution: VALID 8 (7 definitions, 1 JSON string); FORMAT_INVALID not_parseable 2, not_exactly_one_statement 2, not_a_single_json_value 2.
   - Per-call VALID rate on solvable tasks: 0.64 (control) vs 0.58 (treatment).
   - None of these swaps is an established effect.
3. **Existing-guard invariant:** 0 FORMAT_INVALID proposals executed in any arm.
4. **Insufficient-evidence executed mutations (prominent, descriptive):** 1 in treatment (`mathlib_rounding_policy`), equal to control. `textkit_style_guide` stayed FORMAT_INVALID.
5. **Interpretation limits:** one temperature-0 dev run; low power (3 convertible tasks in control); the F threshold was fixed before exposure.
6. **Still unknown:** what dominates replacement correctness. Q-002 stays open.
7. **Execution methodology (not EXP-22 scientific evidence):** the drift arm, run warm in batches of 5 and 2, reproduced the frozen control's model-visible trajectories on 20/20 tasks. This supports warm sequential execution; see METH-007 and MNT-06.

### Furthest-reached bottleneck taxonomy — methodology freeze (2026-09-15; diagnostic analysis, not an experiment)
- Classification: diagnostic-analysis methodology. Not an experiment, not an EXP gate, no capability claim, no Q-002 conclusion.
- Frozen artifacts (SHA-256):
  - specification `benchmark/analysis/furthest_bottleneck_taxonomy.md` `cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5`
  - classifier `benchmark/analysis/furthest_bottleneck.py` `6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b`
  - mutation runner `benchmark/analysis/furthest_bottleneck_mutations.py` `8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a`
  - primary tests `tests/test_furthest_bottleneck.py` `055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451`
  - mutation tests `tests/test_furthest_bottleneck_mutations.py` `658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615`
  - superseded specification `bb706b8f…`: must not be used for classification
- Development evidence (synthetic and task-definition data only; no real trajectory was used):
  - 100/100 synthetic checks passed
  - 30/30 mutation expectations satisfied: 29 caught, 1 equivalent (`unclassifiable_as_valid`, proven by the caught combined mutation `unclassifiable_as_resolved_and_valid`)
  - defects found and fixed during development: a vacuous assertion, mutation-loader contamination risk, two missing mutation protections, JSON-root ambiguity, insertion/action-space distinction
- Approved interpretation:
  - D0_HARNESS is normative. FALSE → INTERFACE_UNSUPPORTED, outside F0–F8 and excluded from the model-bottleneck denominator. UNKNOWN → UNDETERMINED, with the conservative UNKNOWN behavior not weakened.
  - D0_CONTRACT is descriptive only.
  - Reference-added names count as relevant intent.
  - Guard judgements A/B/C describe the proposal counterfactual, not guard policy.
  - F6 subtypes are secondary and descriptive.
- Freeze rule: the methodology is not modified after freezing. A defect or genuine ambiguity found during real classification stops classification, is reported, is not silently repaired, and requires a versioned, reviewed methodology amendment before restarting.
- No UNKNOWN-rate threshold and no classification expectations are registered in advance.
- Status at freeze: real-row classification, taxonomy frequencies and real-trajectory oracle replay have not been performed; classification needs separate authorization.
