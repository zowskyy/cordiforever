#!/usr/bin/env python
"""
Capacity Calculator — 33k window tunable for cordiiv2 pool philosophy.

Given max_tokens, guidance_tokens (lite vs full), per_file_tokens, delta_overhead,
outputs maximum safe file window and recommended max_rounds for 1.5B vs larger models.

Uses only pre-existing deterministic math — no LLM, no new dependencies.
Portable as you add tools/templates: just re-measure guidance/per_file/delta and rerun.

First principles:
- 33k ctx = 32768, but single pruner budget is 30000 for 1.5b (core/context.py MODEL_PRESETS) leaving ~2768 headroom.
- Total window = guidance + N * per_file + folds * delta + fixed overhead (ledger base, system msgs)
- Folds trigger when estimated_tokens > pruner_budget or messages > max_messages (per-model, core/context.py)
- 1.5B hallucination: needs ~1.3 rounds per file (duplicate block, retries), larger ~1.05

Formula:
  tokens = guidance + base_overhead + N * per_file + folds * delta
  folds trigger when tokens > pruner_budget or messages > max_messages
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# The script may be run as `python scripts/capacity_calculator.py` from the
# repo root; make the repo root importable so the shared preset table loads.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.calibration import MODEL_PRESETS  # noqa: E402  (single source of truth)


# Anchors (measured 2026-08-25, 1.5B, 100-file sample)
# Update these values when you re-measure guidance/per_file/delta after adding tools/templates.
ANCHORS = {
    "lite_guidance": 70,
    "full_guidance": 419,
    "per_file_template": 100,
    "per_file_full": 205,
    "delta_fold": 13,
    "delta_full": 40,
    "base_overhead": 30,
}


def load_json_blob(value: str) -> dict:
    """
    Try to parse value as JSON; if that fails, treat as a file path and load from disk.
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        path = Path(value)
        if not path.exists():
            raise ValueError(f"Invalid JSON or file path: {value}")
        return json.loads(path.read_text())


def estimate_window(
    max_tokens: int,
    guidance_tokens: int,
    per_file_tokens: int,
    delta_overhead: int,
    base_overhead: int = 30,
    safety: float = 0.85,
    max_messages: int = 40,
    rounds_per_file: float = 1.3,
    pruner_budget: int | None = None,
    token_keep: float = 0.4,
    msg_keep: float = 0.6,
) -> dict:
    """
    Stepwise simulation matching the loop fold trigger + core/context_pruner.py:26.
    - Folds trigger when tokens > pruner_budget OR messages > max_messages
    - Fold effect: tokens = tokens*keep + delta, messages = messages*keep +1
    - Reports safe window (no fold needed) as max_files, plus folded estimate.
    """
    effective = int(max_tokens * safety)
    if pruner_budget is None:
        pruner_budget = effective

    # Safe window (no fold) — linear, for planning 100% success before history loss
    max_by_tokens = max(0, (effective - guidance_tokens - base_overhead) // max(per_file_tokens, 1))
    max_by_messages = max(0, (max_messages - 2) // max(int(2 * rounds_per_file), 1))
    safe_files = min(max_by_tokens, max_by_messages, 100)

    # Folded estimate: simulate stepwise to see folds needed at safe_files
    tokens = guidance_tokens + base_overhead + safe_files * per_file_tokens
    messages = 2 + int(2 * rounds_per_file * safe_files)
    folds = 0
    # If safe_files would already trigger fold, reduce by 1 fold cost to be safe
    if tokens > pruner_budget or messages > max_messages:
        folds = 1
        tokens = int(tokens * token_keep) + delta_overhead
        messages = int(messages * msg_keep) + 1

    return {
        "max_files": safe_files,
        "effective_budget": effective,
        "tokens_at_max": guidance_tokens + base_overhead + safe_files * per_file_tokens,
        "messages_at_max": 2 + int(2 * rounds_per_file * safe_files),
        "utilization": round((guidance_tokens + base_overhead + safe_files * per_file_tokens) / effective * 100, 1) if effective else 0,
        "folds": folds,
        "tokens_after_fold": tokens,
        "messages_after_fold": messages,
    }


def recommended_rounds(files: int, rounds_per_file: float, buffer: int = 2) -> int:
    return max(4, math.ceil(files * rounds_per_file + buffer))


def solve_for_param(
    target_files: int,
    param: str,
    base_g: int,
    base_pf: int,
    base_d: int,
    max_tokens: int,
    base_overhead: int,
    safety: float,
    max_messages: int,
    rounds_per_file: float,
    pruner_budget: int | None,
) -> dict:
    """Binary-search param (guidance/per_file/delta) to achieve at least target_files."""
    low, high = {
        "guidance": (10, 600),
        "per_file": (20, 400),
        "delta": (5, 100),
    }[param]

    def files_for(value: int) -> int:
        kwargs = {
            "guidance_tokens": base_g if param != "guidance" else value,
            "per_file_tokens": base_pf if param != "per_file" else value,
            "delta_overhead": base_d if param != "delta" else value,
        }
        est = estimate_window(
            max_tokens=max_tokens,
            base_overhead=base_overhead,
            safety=safety,
            max_messages=max_messages,
            rounds_per_file=rounds_per_file,
            pruner_budget=pruner_budget,
            **kwargs,
        )
        return est["max_files"]

    # For guidance/per_file/delta, lower values increase capacity — check feasibility at low extreme
    # Actually for these params, lower is better (less tokens), so check at low
    # If even at most permissive (low) we can't reach target, infeasible
    if files_for(low) < target_files:
        # Try even at lowest, still not enough — actually need even lower than low, but low is already min
        # So infeasible if even low can't reach
        # For guidance, low=10 is min; if that still < target, infeasible
        achieved = files_for(low)
        return {"param": param, "value": low, "achieved_files": achieved, "target_files": target_files, "feasible": False}

    # Binary search for minimal value that achieves target (for guidance/per_file/delta, lower is better, so we search for max feasible that still achieves)
    # We want smallest value that still achieves target — but since lower is better, the minimal that achieves is actually low, trivial.
    # Instead we want maximal allowable value that still achieves target (upper bound)
    # So search for highest value where files_for(value) >= target
    best = low
    lo, hi = low, high
    while lo <= hi:
        mid = (lo + hi) // 2
        achieved = files_for(mid)
        if achieved >= target_files:
            best = mid
            lo = mid + 1  # try higher (less aggressive) still achieving
        else:
            hi = mid - 1

    # Now best is highest value that still achieves; we want the threshold — so step one more to find minimal failing +1
    # Actually to report "must be <= X", we want the highest feasible; best is that.
    achieved = files_for(best)
    return {"param": param, "value": best, "achieved_files": achieved, "target_files": target_files, "feasible": True}


def main():
    p = argparse.ArgumentParser(description="cordiiv2 capacity calculator — 33k window tunable. Formula: tokens = guidance + base + N*per_file + folds*delta, folds trigger when tokens > pruner_budget or messages > max_messages")
    p.add_argument("--max-tokens", type=int, default=None, help="Model context window (e.g., 32768)")
    p.add_argument("--guidance-tokens", type=int, default=None, help="Guidance tokens (lite 70, full 419). If omitted, shows both")
    p.add_argument("--per-file-tokens", type=int, default=None, help="Per file tokens (template 100, full 205). If omitted, shows both")
    p.add_argument("--delta-overhead", type=int, default=None, help="Delta per fold (13 delta, 40 full)")
    p.add_argument("--model", choices=["1.5b", "7b", "14b", "custom"], default="1.5b", help="Preset model profile")
    p.add_argument("--safety", type=float, default=None, help="Safety factor 0.0-1.0 (default per model)")
    p.add_argument("--json", action="store_true", help="Output JSON")
    p.add_argument("--csv", action="store_true", help="Output CSV")
    p.add_argument("--target-files", type=int, default=None, help="Target file window (e.g., 30)")
    p.add_argument("--solve-for", choices=["guidance", "per_file", "delta"], default=None, help="Parameter to solve for to reach --target-files")
    p.add_argument("--verify", type=str, default=None, help="JSONL log of runs to compare predicted vs observed")
    p.add_argument("--diff", nargs=2, metavar=("LEFT", "RIGHT"), default=None, help="Compare two calibration JSON blobs or files and print changed keys")
    p.add_argument("--quiet", action="store_true", help="Print only max_files for best config")
    p.add_argument("--dump-preset", action="store_true", help="Print MODEL_PRESETS entry for --model and exit")
    args = p.parse_args()

    if args.dump_preset:
        print(json.dumps(MODEL_PRESETS[args.model], indent=2))
        return

    if args.diff:
        left = load_json_blob(args.diff[0])
        right = load_json_blob(args.diff[1])
        all_keys = sorted(set(left) | set(right))
        for key in all_keys:
            l = left.get(key)
            r = right.get(key)
            if l == r:
                print(f"  {key}: unchanged")
            else:
                print(f"  {key}: {l} -> {r}")
        return

    if args.safety is not None and not (0 < args.safety <= 1):
        p.error("--safety must be in (0, 1]")
    if args.guidance_tokens is not None and args.guidance_tokens <= 0:
        p.error("--guidance-tokens must be positive")
    if args.per_file_tokens is not None and args.per_file_tokens <= 0:
        p.error("--per-file-tokens must be positive")
    if args.delta_overhead is not None and args.delta_overhead <= 0:
        p.error("--delta-overhead must be positive")

    if args.model != "custom" and args.max_tokens is None:
        preset = MODEL_PRESETS[args.model]
        max_tokens = preset["max_tokens"]
        safety = args.safety if args.safety is not None else preset["safety"]
        max_messages = preset["max_messages"]
        rounds_per_file = preset["rounds_per_file"]
        label = preset["label"]
        pruner_budget = preset["pruner_budget"]
    else:
        max_tokens = args.max_tokens or 32768
        safety = args.safety if args.safety is not None else 0.85
        max_messages = 200
        rounds_per_file = 1.05
        label = f"custom max_tokens={max_tokens}"
        pruner_budget = None

    if args.guidance_tokens is None and args.per_file_tokens is None:
        combos = [
            ("lite+TEMPLATE (current 3x)", ANCHORS["lite_guidance"], ANCHORS["per_file_template"], ANCHORS["delta_fold"]),
            ("lite+full-content", ANCHORS["lite_guidance"], ANCHORS["per_file_full"], ANCHORS["delta_full"]),
            ("full+TEMPLATE", ANCHORS["full_guidance"], ANCHORS["per_file_template"], ANCHORS["delta_fold"]),
            ("full+full-content (baseline)", ANCHORS["full_guidance"], ANCHORS["per_file_full"], ANCHORS["delta_full"]),
        ]
    else:
        g = args.guidance_tokens if args.guidance_tokens is not None else ANCHORS["lite_guidance"]
        pf = args.per_file_tokens if args.per_file_tokens is not None else ANCHORS["per_file_template"]
        d = args.delta_overhead if args.delta_overhead is not None else ANCHORS["delta_fold"]
        combos = [(f"custom g={g} pf={pf} d={d}", g, pf, d)]

    # Inverse solve early return
    if args.target_files is not None and args.solve_for is not None:
        base_name, base_g, base_pf, base_d = combos[0]
        # Find nominal result for base to use as reference
        base_est = estimate_window(max_tokens, base_g, base_pf, base_d, base_overhead=ANCHORS["base_overhead"], safety=safety, max_messages=max_messages, rounds_per_file=rounds_per_file, pruner_budget=pruner_budget)
        solution = solve_for_param(args.target_files, args.solve_for, base_g, base_pf, base_d, max_tokens, ANCHORS["base_overhead"], safety, max_messages, rounds_per_file, pruner_budget)
        if args.json:
            print(json.dumps({"model": label, "solution": solution, "base": base_est}, indent=2))
            return
        if not solution["feasible"]:
            print(f"Infeasible: even at extreme {args.solve_for}, max files = {solution['achieved_files']} < {args.target_files}")
        else:
            print(f"To hit {args.target_files} files on {label}:")
            print(f"  {args.solve_for} <= {solution['value']} (current {base_g if args.solve_for=='guidance' else base_pf if args.solve_for=='per_file' else base_d})")
            print(f"  Achieved: {solution['achieved_files']} files")
        return

    # Variance expansion
    variance_factors = [0.9, 1.0, 1.15]
    results = []
    for name, g, pf, d in combos:
        for factor in variance_factors:
            pf_var = int(pf * factor)
            est = estimate_window(
                max_tokens=max_tokens,
                guidance_tokens=g,
                per_file_tokens=pf_var,
                delta_overhead=d,
                base_overhead=ANCHORS["base_overhead"],
                safety=safety,
                max_messages=max_messages,
                rounds_per_file=rounds_per_file,
                pruner_budget=pruner_budget,
            )
            est["name"] = f"{name} (pf×{factor:.2f})" if len(variance_factors) > 1 else name
            est["guidance"] = g
            est["per_file"] = pf_var
            est["delta"] = d
            est["variance_factor"] = factor
            est["recommended_rounds"] = recommended_rounds(est["max_files"], rounds_per_file)
            est["rounds_per_file"] = rounds_per_file
            results.append(est)

    # For normal table, collapse variance to nominal only for readability unless json/csv
    display_results = [r for r in results if r.get("variance_factor", 1.0) == 1.0] if not args.json and not args.csv else results

    if args.csv:
        import csv
        import sys
        writer = csv.DictWriter(sys.stdout, fieldnames=["config", "guidance", "per_file", "delta", "max_files", "tokens", "messages", "util", "rounds"])
        writer.writeheader()
        for r in results:
            writer.writerow({"config": r["name"], "guidance": r["guidance"], "per_file": r["per_file"], "delta": r["delta"], "max_files": r["max_files"], "tokens": r["tokens_at_max"], "messages": r["messages_at_max"], "util": r["utilization"], "rounds": r["recommended_rounds"]})
        return

    if args.json:
        print(json.dumps({"model": label, "max_tokens": max_tokens, "safety": safety, "results": results}, indent=2))
        return

    if args.quiet:
        best = max(display_results, key=lambda x: x["max_files"])
        print(best["max_files"])
        return

    print(f"Capacity Calculator — {label}")
    print(f"max_tokens={max_tokens} safety={safety} => effective_budget={int(max_tokens*safety)} max_messages={max_messages} rounds/file={rounds_per_file} pruner_budget={pruner_budget}")
    print("")
    print(f"{'Config':<36} {'guid':>4} {'/file':>5} {'delta':>5} | {'max_files':>9} {'tokens':>6} {'msgs':>4} {'util%':>5} {'rounds':>6} {'folds':>5}")
    print("-" * 105)
    for r in display_results:
        print(f"{r['name']:<36} {r['guidance']:>4} {r['per_file']:>5} {r['delta']:>5} | {r['max_files']:>9} {r['tokens_at_max']:>6} {r['messages_at_max']:>4} {r['utilization']:>5}% {r['recommended_rounds']:>6} {r['folds']:>5}")

    # Variance summary
    if len(results) > len(display_results):
        print("")
        print("Variance bands (per_file ×0.9/1.0/1.15):")
        for name in [c[0] for c in combos]:
            vals = [r for r in results if r["name"].startswith(name)]
            if vals:
                print(f"  {name}: {' / '.join(str(v['max_files']) for v in vals)} files")

    print("")
    best = max(display_results, key=lambda x: x["max_files"])
    print(f"Best for this model: {best['name']} => {best['max_files']} files, {best['recommended_rounds']} rounds")
    print("")
    print("Tuning: re-measure after adding tools/templates:")
    print("  guidance = Summarizer.estimate_tokens(tool_guidance)")
    print("  per_file = avg tokens of write_file JSON + content (TEMPLATE short vs full)")
    print("  delta    = len(ledger delta) //4  (now 13 vs 40)")
    print(f"  Example: python scripts/capacity_calculator.py --max-tokens {max_tokens} --guidance-tokens <new> --per-file-tokens <new> --delta-overhead <new> --model {args.model}")
    lite_template = next((r for r in display_results if "lite+TEMPLATE" in r["name"]), None)
    baseline = next((r for r in display_results if "baseline" in r["name"]), None)
    if lite_template and baseline and baseline["max_files"]:
        print("")
        print(f"3x check: lite+TEMPLATE {lite_template['max_files']} files vs baseline {baseline['max_files']} files = {round(lite_template['max_files']/max(baseline['max_files'],1),1)}x")
    print("")
    print("Assumptions: 2*rounds_per_file msgs/file, token_keep=0.4, msg_keep=0.6, folds trigger when tokens>pruner_budget or msgs>max_messages")
    print("Formula: tokens = guidance + base + N*per_file + folds*delta")

    if args.verify:
        import json as jsonlib
        with open(args.verify) as f:
            runs = [jsonlib.loads(line) for line in f if line.strip()]
        observed_files = [r["files_touched"] for r in runs if "files_touched" in r]
        observed_tokens = [r["tokens"] for r in runs if "tokens" in r]
        success_rate = sum(1 for r in runs if r.get("success", False)) / len(runs) if runs else 0
        nominal = next((r for r in display_results if "lite+TEMPLATE" in r["name"]), display_results[0])
        print("")
        print("Verification vs observed runs:")
        print(f"  Predicted max_files: {nominal['max_files']}")
        print(f"  Observed max_files:  max={max(observed_files) if observed_files else 'n/a'}, avg={sum(observed_files)/len(observed_files) if observed_files else 'n/a'}")
        print(f"  Predicted tokens @max: {nominal['tokens_at_max']}")
        print(f"  Observed tokens avg:   {sum(observed_tokens)/len(observed_tokens) if observed_tokens else 'n/a'}")
        print(f"  Success rate: {success_rate:.2%}")
        if observed_files and max(observed_files) < nominal["max_files"] * 0.88:
            print("  Model overestimates capacity; consider safety 0.85 -> 0.90")
        elif observed_files and max(observed_files) > nominal["max_files"] * 1.05:
            print("  Model underestimates capacity; could lower safety slightly")
        return


if __name__ == "__main__":
    main()
