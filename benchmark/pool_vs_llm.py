"""Benchmark: Pool vs LLM-only on math queries."""
from __future__ import annotations

import sys
import time
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from main import build_application


def disable_pool():
    from plugins.agent import loop as loop_module
    from plugins.agent import semantic_router as sr_module
    
    loop_module.try_math_router = lambda text, ctx: None
    loop_module.try_datetime_router = lambda text, ctx: None
    loop_module.try_units_router = lambda text, ctx: None
    
    original_route = sr_module.SemanticRouter.route
    def disabled_route(self, text):
        return None
    sr_module.SemanticRouter.route = disabled_route


def run_benchmark(workspace: Path, model: str, queries: list[str], pool_enabled: bool):
    db_path = workspace / "benchmark.db"
    ctx, reg = build_application(workspace, model, "http://127.0.0.1:11434", db_path)
    
    if not pool_enabled:
        disable_pool()
    
    results = []
    try:
        agent = ctx.plugins["agent_loop"]
        for q in queries:
            start = time.time()
            answer = agent.run(q)
            elapsed = time.time() - start
            
            results.append({
                "query": q,
                "answer": str(answer)[:100],
                "time": round(elapsed, 2),
                "pool_hit": pool_enabled,
            })
            print(f"  [{elapsed:.2f}s] {q[:50]}... -> {str(answer)[:50]}")
    finally:
        reg.stop_all()
    
    return results


def main():
    workspace = Path("workspace").resolve()
    queries = [
        "What is the derivative of x squared times sine of x?",
        "Evaluate x squared at x equals 3",
        "What is 2 plus 2?",
        "Solve x squared minus 4 equals 0",
        "What is the derivative of x cubed?",
        "Integrate x squared",
        "What is the square root of 16?",
        "What is the limit of (x^2-1)/(x-1) as x approaches 1?",
    ]
    
    model = "qwen2.5-coder:1.5b"
    
    print(f"Benchmark: Pool vs LLM-only")
    print(f"Model: {model}")
    print(f"Queries: {len(queries)}")
    print()
    
    print("=== WITH POOL ===")
    pool_results = run_benchmark(workspace, model, queries, pool_enabled=True)
    
    print()
    print("=== WITHOUT POOL ===")
    no_pool_results = run_benchmark(workspace, model, queries, pool_enabled=False)
    
    print()
    print("=== COMPARISON ===")
    print(f"{'Query':<50} {'Pool (s)':<10} {'No Pool (s)':<12} {'Speedup':<10}")
    print("-" * 80)
    for p, np in zip(pool_results, no_pool_results):
        speedup = np["time"] / p["time"] if p["time"] > 0 else 0
        print(f"{p['query'][:50]:<50} {p['time']:<10.2f} {np['time']:<12.2f} {speedup:<10.1f}x")
    
    pool_avg = sum(r["time"] for r in pool_results) / len(pool_results)
    no_pool_avg = sum(r["time"] for r in no_pool_results) / len(no_pool_results)
    print("-" * 80)
    print(f"{'AVERAGE':<50} {pool_avg:<10.2f} {no_pool_avg:<12.2f} {no_pool_avg/pool_avg:<10.1f}x")
    
    Path("benchmark_results").mkdir(exist_ok=True)
    with open("benchmark_results/pool_vs_llm.json", "w") as f:
        json.dump({
            "model": model,
            "queries": len(queries),
            "pool_results": pool_results,
            "no_pool_results": no_pool_results,
            "pool_avg": pool_avg,
            "no_pool_avg": no_pool_avg,
            "speedup": no_pool_avg / pool_avg if pool_avg > 0 else 0,
        }, f, indent=2)
    print(f"\nResults saved to benchmark_results/pool_vs_llm.json")


if __name__ == "__main__":
    main()
