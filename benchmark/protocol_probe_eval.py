"""Protocol probes: can a model reliably select, encode, and execute unambiguous actions?

Each probe is one user request with exactly one correct action. Three layers are scored separately so a wrong
choice is never confused with a serialization failure:
  semantic_choice_correct - the first interpreted call is the expected tool with the expected arguments
  protocol_encoding       - native (Ollama tool_calls field) | text_json (parsed from content) | invalid
  executed                - the call ran through AgentLoop._execute_tool_call without error

Usage:
    python benchmark/protocol_probe_eval.py --condition all
    python benchmark/protocol_probe_eval.py --condition all --summary-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.repo_task_eval import CONDITIONS as REPO_CONDITIONS
from benchmark.repo_task_eval import (
    OLLAMA,
    REPOS_DIR,
    _tree_hash,
    append_row,
    harness_hash,
    load_rows,
    model_digest,
    residency_snapshot,
    unload_model,
)
from core.errors import ModelError
from core.messages import Message
from core.path_candidates import normalize
from core.tool_call_extraction import extract_tool_calls_from_text
from main import build_application
from plugins.agent.loop import LITE_COMPACT_GUIDANCE, REPO_TOOLS_GUIDANCE

RESULTS = REPO_ROOT / "benchmark" / "results" / "protocol_probe_eval.jsonl"
PROBE_REPO = "mathlib"
CONDITIONS = {name: {**cfg, "overrides": {**cfg["overrides"], "repo_tools": True}} for name, cfg in REPO_CONDITIONS.items()}


@dataclass(frozen=True)
class Probe:
    name: str
    prompt: str
    tool: str
    args: dict[str, Any]


PROBES: list[Probe] = [
    Probe("read_operations", "Read mathlib/operations.py.", "read_file", {"path": "mathlib/operations.py"}),
    Probe("open_calculator", "Open calculator.py.", "read_file", {"path": "calculator.py"}),
    Probe("read_tests", "Read tests/test_core.py.", "read_file", {"path": "tests/test_core.py"}),
    Probe("list_mathlib", "List the files in the mathlib folder.", "list_directory", {"path": "mathlib"}),
    Probe("outline_explicit", "Show the repository outline.", "repo_outline", {}),
    Probe("outline_paraphrase", "Give me a map of the files in this repository.", "repo_outline", {}),
    Probe("find_symbol_explicit", "Find symbol subtract.", "find_symbol", {"name": "subtract"}),
    Probe("find_symbol_question", "Where is the evaluate function defined?", "find_symbol", {"name": "evaluate"}),
    Probe("references_explicit", "Find references to median.", "find_references", {"symbol": "median"}),
    Probe("references_paraphrase", "Find every place that uses the add function.", "find_references", {"symbol": "add"}),
    Probe("tests_for_symbol", "Find the tests for subtract.", "find_tests", {"target": "subtract"}),
    Probe("tests_for_file", "Which tests cover mathlib/stats.py?", "find_tests", {"target": "mathlib/stats.py"}),
    Probe("cone_explicit", "Show the dependency cone of mathlib/operations.py.", "dependency_cone", {"target": "mathlib/operations.py"}),
    Probe("cone_paraphrase", "What does calculator.py import, and what imports it?", "dependency_cone", {"target": "calculator.py"}),
    Probe("delete_legacy", "Delete legacy/operations.py.", "delete_file", {"path": "legacy/operations.py"}),
]


def _normalize_arg(key: str, value: Any) -> Any:
    if isinstance(value, str) and key in ("path", "target"):
        return normalize(value)
    return value


def args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    return all(_normalize_arg(k, actual.get(k)) == _normalize_arg(k, v) for k, v in expected.items())


def system_prompt() -> str:
    return json.dumps({"role": "system", "content": LITE_COMPACT_GUIDANCE + REPO_TOOLS_GUIDANCE}, ensure_ascii=False)


def run_probe(probe: Probe, condition: str) -> dict[str, Any]:
    config = CONDITIONS[condition]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cordii-probe-") as tmp:
        workspace = Path(tmp) / "ws"
        shutil.copytree(REPOS_DIR / PROBE_REPO, workspace, ignore=shutil.ignore_patterns("__pycache__"))
        ctx, reg = build_application(workspace, config["model"], OLLAMA, Path(tmp) / "probe.db", profile="lite", calibration_overrides=config["overrides"])
        try:
            model = ctx.plugins["ollama_model"]
            loop = ctx.plugins["agent_loop"]
            schemas = loop._get_active_tool_schemas()
            messages = [Message("system", system_prompt()), Message("user", probe.prompt)]
            raw_content, native_calls, error = "", None, None
            try:
                data = model._post_chat(messages, schemas, stream=False).json()
                raw = data.get("message") or {}
                raw_content = raw.get("content") or ""
                native_calls = raw.get("tool_calls") or None
            except (ModelError, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"
            tool_calls = native_calls or (extract_tool_calls_from_text(raw_content, schemas) if raw_content else [])
            encoding = "native" if native_calls else ("text_json" if tool_calls else "invalid")
            _, interpreted = loop._interpret_response(Message("assistant", raw_content, tool_calls=tool_calls or None), schemas)
            first = interpreted[0] if interpreted else None
            fn = (first or {}).get("function", {})
            actual_args = fn.get("arguments") or {}
            if isinstance(actual_args, str):
                try:
                    actual_args = json.loads(actual_args)
                except json.JSONDecodeError:
                    actual_args = {}
            choice_correct = fn.get("name") == probe.tool and args_match(probe.args, actual_args)
            executed, execution_detail = False, None
            if first is not None:
                try:
                    result = loop._execute_tool_call(first)
                    executed = not (isinstance(result, str) and result.lstrip().startswith('{"error"'))
                    execution_detail = str(result)[:200]
                except Exception as exc:  # recorded as a failed execution with its cause
                    execution_detail = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            reg.stop_all()
    return {
        "probe": probe.name, "condition": condition, "model": config["model"], "expected_tool": probe.tool,
        "chosen_tool": fn.get("name"), "chosen_args": actual_args, "semantic_choice_correct": choice_correct,
        "protocol_encoding": encoding, "executed": executed, "execution_detail": execution_detail,
        "raw_content": raw_content[:500], "model_error": error, "seconds": round(time.perf_counter() - started, 1),
    }


def probe_fingerprint(probe: Probe, condition: str, digest: str, harness: str, repo_hash: str) -> str:
    payload = {"probe": asdict(probe), "condition": condition, "overrides": CONDITIONS[condition]["overrides"], "model": CONDITIONS[condition]["model"],
               "digest": digest, "harness": harness, "repo": repo_hash, "system_prompt": system_prompt(),
               "probe_source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    encodings: dict[str, int] = {}
    for r in rows:
        encodings[r["protocol_encoding"]] = encodings.get(r["protocol_encoding"], 0) + 1
    choice_given_valid = [r for r in rows if r["protocol_encoding"] != "invalid"]
    return {
        "probes": n,
        "semantic_choice_correct": f"{sum(r['semantic_choice_correct'] for r in rows)}/{n}",
        "protocol_encodings": encodings,
        "executed": f"{sum(r['executed'] for r in rows)}/{n}",
        "correct_and_executed": f"{sum(r['semantic_choice_correct'] and r['executed'] for r in rows)}/{n}",
        "choice_correct_given_valid_encoding": f"{sum(r['semantic_choice_correct'] for r in choice_given_valid)}/{len(choice_given_valid)}",
        "wrong_choices": {r["probe"]: r["chosen_tool"] for r in rows if not r["semantic_choice_correct"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Protocol probes: choice, encoding, execution")
    parser.add_argument("--condition", choices=[*CONDITIONS, "all"], default="all")
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    results = Path(args.results)
    harness = harness_hash()
    repo_hash = _tree_hash(REPOS_DIR / PROBE_REPO)
    summary: dict[str, Any] = {}
    for condition in (list(CONDITIONS) if args.condition == "all" else [args.condition]):
        model = CONDITIONS[condition]["model"]
        digest = model_digest(model)
        fingerprints = {p.name: probe_fingerprint(p, condition, digest, harness, repo_hash) for p in PROBES}
        done = {r["probe"] for r in load_rows(results) if r.get("condition") == condition and fingerprints.get(r.get("probe")) == r.get("fingerprint")}
        if not args.summary_only:
            append_row(results.with_name("protocol_probe_residency.jsonl"), residency_snapshot(condition, "before"))
            for probe in PROBES:
                if probe.name in done:
                    continue
                row = run_probe(probe, condition)
                row["fingerprint"] = fingerprints[probe.name]
                append_row(results, row)
                print(json.dumps({k: row[k] for k in ("condition", "probe", "chosen_tool", "semantic_choice_correct", "protocol_encoding", "executed")}), flush=True)
            append_row(results.with_name("protocol_probe_residency.jsonl"), residency_snapshot(condition, "after_run"))
            released = unload_model(model)
            append_row(results.with_name("protocol_probe_residency.jsonl"), {**residency_snapshot(condition, "after_unload"), "model_unloaded": released})
        latest = {}
        for row in load_rows(results):
            if row.get("condition") == condition and fingerprints.get(row.get("probe")) == row.get("fingerprint"):
                latest[row["probe"]] = row
        summary[condition] = {"complete": len(latest) == len(PROBES), **summarize(list(latest.values()))}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
