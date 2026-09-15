# Baseline Validation — Cordi v2

## Milestone
- **Tag:** `v2.0-baseline-stable`
- **Commit:** `f9cef7b`
- **Date:** 2026-08-30
- **Model:** `qwen2.5-coder:1.5b`

## Proof Artifacts

### Deterministic suite
```powershell
pytest --basetemp C:\tmp\pytest_cordiiv2 -q
```
**Expected:** 279 passed, 7 skipped

### Live integration suite
```powershell
pytest --basetemp C:\tmp\pytest_cordiiv2 --live -k integration -q
```
**Expected:** 4 passed (all live 1.5B integration tests green)

### Baseline gate script
```powershell
powershell -File scripts/baseline_gate.ps1
```
Runs both suites and asserts the counts above. Add `-SkipLive` to run only the deterministic gate.

## Invariants Proven
- **1.5B stability** — single-pruner token+message pass, tool-result truncation to calibrated byte cap
- **33k context hygiene** — pruner budget 30000, KV headroom ~2768, folds trigger on tokens OR messages
- **Zero-token `lite`** — 19 plugins, deterministic routing only, no LLM calls unless `full` + `--enable-semantic-router`
- **Calibration centralization** — `validate_calibration()` wired into `resolve_calibration()`; all per-model numbers sourced from `core/context.py` `MODEL_PRESETS`
- **Profile isolation** — `lite` excludes `semantic_router` and `embedding_model`; `AgentLoop._semantic_router` is `None`
- **Injection hardening** — injections inserted as `user` with `[injected context]` prefix
- **Event hygiene** — exactly one `turn.start`/`turn.end`, one `turn.round` per iteration

## Invariants proven by this baseline
- **1.5B stability on `qwen2.5-coder:1.5b`** — single-pruner token+message pass preserves coherence; tool-result truncation prevents window blowup.
- **4k context hygiene** — pruner budget 3000, KV headroom 1000, folds trigger on tokens OR messages.
- **Zero-token `lite`** — 19 plugins, deterministic routing only; no LLM calls unless `full` + `--enable-semantic-router`.
- **Calibration centralized** — all per-model numbers live in `core/context.py:28–34`; invariant layers read via `calibration_from_context()`.
- **Profile isolation** — `lite` excludes `semantic_router` and `embedding_model`; `AgentLoop._semantic_router` is `None`.
- **Injection hardening** — injections inserted as `user` with `[injected context]` prefix.
- **Event hygiene** — exactly one `turn.start`/`turn.end`, one `turn.round` per iteration.

## What is allowed to change without breaking baseline
- New plugins added behind existing invariants and properly wired in `main.py` profile blocks.
- New models added to the calibration table (`core/context.py:28–34`) with corresponding tests.
- Refactors that preserve observable behavior and do not change deterministic/live test counts.
- Test additions that increase pass counts.

## What must not change
- Deterministic pass count dropping below **276** or skipped count exceeding **7**.
- Live integration pass count dropping below **4**.
- `lite` profile touching `semantic_router`, `embedding_model`, or any LLM fallback path.
- Calibration-specific literals spreading into plugin logic, routing, or pruning code.
- Event ownership/emission counts changing without corresponding test updates.
