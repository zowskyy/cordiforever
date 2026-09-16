"""Deterministic producer-envelope verifier for the D3-v2 methodology candidate.

VERIFICATION TOOLING, not methodology. It builds synthetic rows through the REAL producer construction path
(`benchmark.repo_task_eval.call_log`) and asserts that every legitimately produced row satisfies
D3_PRODUCER_ENVELOPE_CONTRACT — i.e. that Layer 0 never rejects something the evaluator can actually emit.

REAL-DATA FIREWALL, structural: no code path here can load an experimental result row. There is no input-path
argument, `benchmark/results/` is never opened, and every timeline is generated internally. `call_log` is called with
a synthetic seed-text mapping built in memory.

Exit code 0 only when every generated row is accepted and the shape invariants hold; nonzero otherwise (fail closed).

Usage:
  python benchmark/analysis/furthest_bottleneck_v2_producer_envelope_check.py [--trials N] [--seed N] [--report PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import benchmark.analysis.furthest_bottleneck_v2 as v2                 # noqa: E402
from benchmark.repo_task_eval import call_log                          # noqa: E402

VERIFIER = Path(__file__)
SEED_TEXTS = {"a.py": "x = 1\n"}
LONG = "L" * 400            # forces _summarize_arg to persist {chars, sha256, head} instead of the string
TOOLS = ("read_file", "diagnose", "edit_symbol", "write_file", "list_directory", "delete_file", "done", "ünknown")
ARG_VALUES = ("a.py", LONG, 7, True, None, ["a.py"], {"nested": 1}, "", "./a.py", "/" * 801)
ARG_KEYS = ("path", "target", "replacement", "content", "evidence", "selector_kind")

#: Fixed adversarial-but-legitimate timelines, including the shapes the fifth review used.
FIXED_TIMELINES: dict[str, list[tuple[str, dict]]] = {
    "summarized_long_arg": [("turn.round", {}), ("tool.result", {"tool": "diagnose", "arguments": {"path": LONG},
                                                                "result": "ok", "success": True})],
    "arguments_absent": [("turn.round", {}), ("tool.result", {"tool": "read_file", "result": "ok", "success": False})],
    "arguments_none": [("turn.round", {}), ("tool.result", {"tool": "read_file", "arguments": None,
                                                            "result": "ok", "success": True})],
    "arguments_empty": [("turn.round", {}), ("tool.result", {"tool": "read_file", "arguments": {},
                                                             "result": "", "success": True})],
    "non_string_path": [("turn.round", {}), ("tool.result", {"tool": "diagnose", "arguments": {"path": 42},
                                                             "result": "ok", "success": True})],
    "none_path": [("turn.round", {}), ("tool.result", {"tool": "edit_symbol", "arguments": {"path": None},
                                                       "result": "ok", "success": False})],
    "nested_dict_arg": [("turn.round", {}), ("tool.result", {"tool": "diagnose", "arguments": {"path": {"a": {"b": 1}}},
                                                             "result": "ok", "success": True})],
    "result_before_any_turn_round": [("tool.result", {"tool": "diagnose", "arguments": {"path": "a.py"},
                                                      "result": "ok", "success": True})],
    "foreign_events_interleaved": [("guard.rejected", {"tool": "diagnose", "path": "a.py", "round": 99}),
                                   ("turn.round", {}), ("model.resampled", {}),
                                   ("tool.result", {"tool": "diagnose", "arguments": {"path": "a.py"},
                                                    "result": "ok", "success": True})],
    "empty_timeline": [],
}


def _random_timeline(rng: random.Random) -> list[tuple[str, dict]]:
    timeline: list[tuple[str, dict]] = []
    for _ in range(rng.randint(0, 12)):
        if rng.random() < 0.3:
            timeline.append(("turn.round", {"round": rng.randint(0, 5)}))
            continue
        arguments = {key: rng.choice(ARG_VALUES) for key in rng.sample(ARG_KEYS, rng.randint(0, 3))}
        payload: dict = {"tool": rng.choice(TOOLS), "arguments": arguments,
                         "result": rng.choice(["ok", LONG, ""]), "success": rng.choice([True, False])}
        if rng.random() < 0.1:
            payload.pop("arguments")
        timeline.append(("tool.result", payload))
        if rng.random() < 0.1:
            timeline.append(("guard.rejected", {"tool": payload["tool"], "path": "a.py", "round": 1, "reason": "x"}))
    return timeline


def _check(name: str, timeline: list[tuple[str, dict]], summary: dict) -> None:
    calls, views = call_log(timeline, SEED_TEXTS)
    row = {"calls": calls, "read_views": views}
    summary["rows_generated"] += 1
    summary["calls_generated"] += len(calls)
    violations = v2.producer_envelope_violations(row)
    if violations:
        summary["rejections"].append({"timeline": name, "violations": violations, "calls": calls[:3]})
    for index, call in enumerate(calls):
        if not isinstance(call.get("args"), dict):
            summary["shape_failures"].append({"timeline": name, "index": index, "field": "args"})
        if type(call.get("round")) is not int:
            summary["shape_failures"].append({"timeline": name, "index": index, "field": "round"})
        if type(call.get("success")) is not bool:
            summary["shape_failures"].append({"timeline": name, "index": index, "field": "success"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=4000, help="randomized producer timelines (seeded)")
    parser.add_argument("--seed", type=int, default=20260915, help="seed for the randomized timelines")
    parser.add_argument("--report", type=Path, default=None, help="write the JSON summary here (output only)")
    parser.add_argument("--commit", default="", help="candidate commit SHA, recorded in the summary")
    args = parser.parse_args(argv)

    summary: dict = {
        "verifier": VERIFIER.name,
        "verifier_sha256": hashlib.sha256(VERIFIER.read_bytes()).hexdigest(),
        "candidate_v2_sha256": hashlib.sha256((ROOT / "benchmark/analysis/furthest_bottleneck_v2.py").read_bytes()).hexdigest(),
        "commit": args.commit, "producer": "benchmark.repo_task_eval.call_log",
        "trials": args.trials, "seed": args.seed, "fixed_timelines": sorted(FIXED_TIMELINES),
        "rows_generated": 0, "calls_generated": 0, "rejections": [], "shape_failures": [],
    }

    for name, timeline in FIXED_TIMELINES.items():
        _check(name, timeline, summary)
    rng = random.Random(args.seed)
    for trial in range(args.trials):
        _check(f"random#{trial}", _random_timeline(rng), summary)

    summary["rejection_count"] = len(summary["rejections"])
    summary["shape_failure_count"] = len(summary["shape_failures"])
    summary["passed"] = (summary["rejection_count"] == 0 and summary["shape_failure_count"] == 0
                         and summary["rows_generated"] > 0 and summary["calls_generated"] > 0)
    text = json.dumps(summary, indent=2, default=str)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
