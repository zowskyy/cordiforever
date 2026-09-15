# Baseline Contract — Cordi v2

## Milestone
- **Tag:** `v2.0-baseline-stable`
- **Commit:** `f9cef7b`
- **Date:** 2026-08-30
- **Model:** `qwen2.5-coder:1.5b`

## How to verify baseline

### One-command health check
```powershell
python scripts/baseline_health.py
```

### Full gate
```powershell
powershell -File scripts/baseline_gate.ps1
```

### Calibration
```powershell
python scripts/capacity_calculator.py --model 1.5b --quiet
```

### Dry-run sanity
```powershell
python main.py --profile lite --dry-run
python main.py --profile full --dry-run
```

## Expected results

| Check | Expected |
|---|---|
| Deterministic tests | ≥288 passed, ≤8 skipped |
| Live integration | ≥4 passed on `qwen2.5-coder:1.5b` |
| Lite plugins | 21 |
| Full plugins | 44 |
| Semantic router in lite | not registered |
| Semantic router in full | disabled unless `--enable-semantic-router` |
| Capacity (best config) | 19 files |

## What is allowed to change without breaking baseline
- New plugins added behind existing invariants and properly wired in `main.py` profile blocks
- New models added to the calibration table (`core/context.py:28–34`) with corresponding tests
- Refactors that preserve observable behavior and do not change deterministic/live test counts
- Test additions that increase pass counts

## What must not change
- Deterministic pass count dropping below **288** or skipped count exceeding **8**
- Live integration pass count dropping below **4**
- `lite` profile touching `semantic_router`, `embedding_model`, or any LLM fallback path
- Calibration-specific literals spreading into plugin logic, routing, or pruning code
- Event ownership/emission counts changing without corresponding test updates
- Plugin counts deviating from **21** (`lite`) or **44** (`full`)

## Related docs
- `docs/baseline_validation.md` — proof artifacts and invariant details
- `AGENTS.md` — repository-wide invariants and development workflow
- `PROJECT_TRACKING.md` — project state and open items
