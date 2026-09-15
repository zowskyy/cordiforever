# Cordi v2 — 1.5B Usage Guide

This guide explains how to use the Cordi v2 harness effectively with `qwen2.5-coder:1.5b` (and similar 1.5B-class models). It covers recommended workflows, when to use each profile, and how to interpret pruner/fold behavior.

## Quick start

```powershell
# Default 1.5B-safe lite profile
python main.py --workspace workspace --model qwen2.5-coder:1.5b --profile lite

# Dry-run check (CI or quick sanity)
python main.py --model qwen2.5-coder:1.5b --profile lite --dry-run

# Lite with verbose schemas (compact_schema off)
python main.py --model qwen2.5-coder:1.5b --profile lite --no-compact-schema

# Full profile with semantic router (debug/analysis, higher token cost)
python main.py --model qwen2.5-coder:1.5b --profile full --enable-semantic-router
```

## Profiles: when to use which

### `lite` (default, recommended for 1.5B)

**Use for:** everyday coding tasks, file edits, small refactors, tool-driven workflows.

**Characteristics:**
- **23 plugins** total (20 explicit + 3 auto-added by `EventLogger`: `event_log`, `continuity`, plus `data_exporter`)
- Zero-token pool: math, datetime, units routing are deterministic/symbolic
- SchemaRouter enabled with compact schemas by default (reduces token overhead)
- ArrayHelper for deterministic array task reasoning (zero-token)
- AppVerifier for deterministic completion checking (zero-token)
- DataExporter for trajectory collection and fine-tuning (zero-token)
- No semantic router, no embeddings, no heavy observability
- Optimized for ~30k token budget within 33k context

**Best practices:**
- Keep file content concise; prefer TEMPLATE-style summaries over full-file dumps when possible.
- Let the deterministic pool handle exact work (math, units, datetime) instead of asking the model to compute.
- Use `--dry-run` before long sessions to confirm plugin counts and profile state.

### `full` (debug/analysis, higher token cost)

**Use for:** deep debugging, tracing, memory experiments, semantic search across workspace.

**Characteristics:**
- **46 plugins** total (43 explicit + 3 auto-added)
- Semantic router available (but **off by default**; enable with `--enable-semantic-router`)
- Observability plugins: tracing, metrics, telemetry, health monitoring
- SchemaRouter in verbose mode by default (pass `--compact-schema` to enable compact)
- Higher token consumption; **not recommended** for routine 1.5B work

**Best practices:**
- Enable semantic router only when you need embedding-based retrieval; it adds token and compute cost.
- Monitor token usage closely; expect more frequent folds/prunes.
- Use `full` for targeted sessions, not as your default 1.5B workflow.

## Capacity and context hygiene

### Expected capacity

For `qwen2.5-coder:1.5b` with default calibration:

```powershell
python scripts/capacity_calculator.py --model 1.5b --quiet
# Expected: 19
```

This means you can safely work with **~19 files** in context before the pruner must fold. If you exceed this, expect history compaction.

### Interpreting folds and pruner logs

The pruner triggers a fold when:

- **Tokens** exceed the pruner budget (~30k for 1.5B), **OR**
- **Messages** exceed the model's `max_messages` limit

When a fold occurs:

- Tokens are reduced to ~40% of their previous value plus a small delta
- Messages are reduced to ~60% plus one
- Older turns are compacted; recent turns are preserved

**Signs you're hitting folds too often:**
- Model loses track of earlier instructions
- Repeated re-explanation of context
- Tool outputs get truncated unexpectedly

**Mitigations:**
- Reduce per-file token usage (shorter templates, summaries)
- Work in smaller batches (fewer files per session)
- Use `full` profile sparingly; it consumes tokens faster

## Recommended workflows

### 1. File edit / refactor session

```powershell
python main.py --workspace workspace --model qwen2.5-coder:1.5b --profile lite
```

- Open only the files you need; avoid dumping entire directories.
- Let the model generate edits via tools; review before applying.
- If context feels tight, close unused files or start a fresh session.

### 2. Math / units / datetime tasks

- Ask the model to use the math/units/datetime tools explicitly.
- Example: "Calculate the total bytes for these 5 files using the math tool."
- The deterministic pool handles exact computation; the model focuses on structure.

### 3. Debugging / tracing

```powershell
python main.py --workspace workspace --model qwen2.5-coder:1.5b --profile full --enable-semantic-router
```

- Use tracing, metrics, and health plugins to inspect behavior.
- Enable semantic router only if you need embedding-based retrieval.
- Keep sessions short; switch back to `lite` for routine work.

### 4. CI / pre-merge checks

```powershell
# Verify baseline invariants
powershell -File scripts/baseline_gate.ps1

# Quick profile check
python main.py --profile lite --dry-run
python main.py --profile full --dry-run
```

Run these before merging changes that affect plugins, calibration, or routing.

## App Completion Verifier

The AppVerifier plugin provides deterministic, evidence-based completion checking.
It translates user requests into concrete file existence and content checks,
blocking premature "done" claims until artifacts are actually complete.

### How it works

1. When the model returns a text response (no tool calls), the verifier runs.
2. It checks that required files exist and contain expected patterns.
3. If verification fails, feedback is injected as a `[verification feedback]`
   user message and the agent continues working.
4. If verification passes, `verification.passed` event is emitted and the
   agent returns its response.

### Supported app patterns

| Pattern       | Detection keywords                    | Checks                                           |
|---------------|----------------------------------------|--------------------------------------------------|
| Todo          | todo, task list                         | HTML exists, JS exists, add fn, delete fn, list element |
| CRUD          | crud, api, endpoint, rest, backend      | Server exists, POST/GET/PUT/DELETE endpoints     |
| Calculator    | calculate, math, sum, total            | HTML exists, JS exists, display, buttons, operations |
| Dashboard     | dashboard, chart, visualization        | HTML exists, container, JS, data source          |
| Auth          | auth, login, signup, session, jwt      | Server exists, login, signup, session, password  |
| E-commerce    | e-commerce, cart, checkout, product      | HTML exists, server exists, product list, cart, checkout |
| Chat          | chat, message, real-time, websocket     | HTML exists, JS exists, message list, send, realtime |
| Data Viz      | data visualization, chart, graph       | HTML exists, JS exists, chart library, data source |
| Generic       | (any request)                          | No TODO/FIXME/placeholder comments               |

### Customizing criteria

To add a new app pattern:

1. Add a keyword set to `AppVerifier` class (e.g., `_MYAPP_KEYWORDS`).
2. Add a `_generate_myapp_criteria()` method that returns
   `VerificationCriterion` objects.
3. Add the detection branch in `define_criteria()`.
4. Update `_generate_generic_criteria()` to include your app's main files.

### Disabling the verifier

The verifier is zero-drag when not relevant (non-app tasks). To disable it
entirely, simply don't register `AppVerifier` in your profile configuration.
The AgentLoop checks `self._app_verifier` and skips verification if it's
`None`.

## Data Export for Fine-Tuning

The DataExporter plugin collects successful session trajectories from the
EventLog and exports them as JSONL for fine-tuning.

### Exporting trajectories

```powershell
# Export all successful sessions to JSONL
python main.py --profile lite --export-data --export-path finetune_data

# This runs, exports, and exits — no interactive loop
```

**Quality filters** applied during export:
- Session must have `outcome: "success"` (recorded by the event logger)
- No `protected_file.violation` events
- Completed within 20 model turns
- No `error`, `timeout`, or `agent.error` events

### Fine-tuning

Once trajectories are exported:

```powershell
# Fine-tune Qwen 1.5B on the exported data
python scripts/fine_tune.py --data-dir finetune_data --output-dir finetune_output --epochs 3 --lr 2e-4

# Swap to the fine-tuned model
python scripts/swap_model.py --model-path finetune_output

# Run continuously (benchmarks → export → fine-tune → swap → compare → sleep)
./scripts/optimize_loop.sh --interval 3600
```

See `scripts/capacity_calculator.py --verify` to re-measure calibration
after swapping models.

### Troubleshooting

**Verification keeps failing**
- Check which criteria are failing via the `verification.failed` event.
- Ensure files exist at the correct workspace-relative paths.
- Check that file content contains the required patterns (case-insensitive).

**Verifier not running**
- Confirm `app_verifier` is registered in the profile.
- Confirm the model returned a text response (no tool calls) to trigger verification.

**False positives on placeholder check**
- The placeholder patterns are case-sensitive (`TODO[: ]`, `FIXME[: ]`) and
  also match `PLACEHOLDER`, `lorem ipsum`, `not implemented`, `to be implemented`.
- If your legitimate code contains these strings, rephrase or use a different
  variable name.

## Troubleshooting

**Model seems to forget earlier instructions**
- Likely hitting folds/prunes. Reduce context size (fewer files, shorter templates).
- Check `logs/baseline_gate.log` for fold frequency.
- Consider raising the safety factor in `capacity_calculator` (e.g., `0.85` → `0.90`).

**Tool outputs get truncated**
- Per-file token cost may be too high. Use TEMPLATE-style summaries.
- Re-measure `per_file_tokens` and update anchors in `scripts/capacity_calculator.py`.

**Semantic router feels slow or expensive**
- It's expected: embeddings add token and compute cost.
- Use only in `full` profile, and only when you need semantic search.
- Keep `lite` as your default for 1.5B work.

## Extending the harness

### Adding new tools/templates
1. Re-measure `guidance`/`per_file`/`delta` after adding the tool.
2. Update `ANCHORS` in `scripts/capacity_calculator.py`.
3. Run `python scripts/capacity_calculator.py --model 1.5b --verify` to confirm predictions.
4. Run the full baseline gate to ensure no regressions.

### Adding new models
1. Add a new entry to `MODEL_PRESETS` in `core/context.py:28–34`.
2. Define `max_tokens`, `safety`, `pruner_budget`, `max_messages`, `rounds_per_file`, `max_tool_result_bytes`.
3. Run `python scripts/capacity_calculator.py --model <new> --verify` with live benchmarks.
4. Update the baseline gate thresholds if needed.

## Summary

- Default to `lite` for 1.5B work; it's token-efficient and deterministic.
- Use `full` sparingly for debugging, tracing, or semantic search.
- Monitor capacity with `python scripts/capacity_calculator.py --model 1.5b --quiet`; expect **19** files for 1.5B.
- Watch for folds; reduce context size if the model loses track of instructions.
- Run the baseline gate before merging changes that affect plugins, calibration, or routing.

This harness is designed to keep 1.5B models productive without token blow-up or silent regressions. Stick to the invariants, and you can iterate safely.

## Related docs

- `docs/baseline_contract.md` — baseline contract and verification commands
- `docs/baseline_validation.md` — proof artifacts and invariant details
- `AGENTS.md` — repository-wide invariants and development workflow
- `PROJECT_TRACKING.md` — project state and open items
- `tests/benchmarks/README.md` — benchmark suite documentation
