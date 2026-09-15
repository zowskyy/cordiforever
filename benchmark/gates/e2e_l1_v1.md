# Gate e2e_l1_v1 — end-to-end L1 targeted grounding (pre-registered 2026-09-14, evaluated: FAILED)

Conditions: `{gemma,qwen}_constrained` vs `{gemma,qwen}_L1` (= same overrides + `targeted_grounding: True`; evidence gate and repo tools off). Dev split, sequential, model unloaded between conditions. Instrument: `benchmark/repo_task_eval.py`.

Per model, L1 vs its constrained run:
- Primary: `oracle_passed_solvable` rises by >= 3 tasks (1-2 = noise).
- Must not regress: `lane_false_verified` stays 0; `false_completion_on_insufficient_evidence` does not rise; `damaged_file_tasks` does not rise.
- Secondary (reported, not decisive): read recall/precision, gold first touch, mutation precision, gold edit recall, escalations, prompt tokens.
- If localization metrics rise but oracle success does not, localization is not the end-to-end bottleneck.

Note: written to a file after evaluation; the text is the pre-registered wording from PROJECT_TRACKING.md. Rows from that run predate row-level gate hashes.
