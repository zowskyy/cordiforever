"""Localization-only benchmark: can the model find WHERE a task lives, without changing anything?

Each solvable RepoTask runs with navigation-only actions (the constrained decoder cannot emit mutations; the loop
refuses any that arrive). The model must finish with a declaration of files and symbols. Scored per task:
  declared file/symbol recall and precision vs gold, first-gold rank over touched files,
  invented-path rate over path-bearing calls, protocol-failure rate over model replies, and writes (must be 0).
Protocol failures are reported separately from localization quality.

Conditions (named factor only): model (gemma vs qwen, both constrained) x repo_tools (off vs on).

Usage:
    python benchmark/localization_eval.py --condition all --split dev
    python benchmark/localization_eval.py --condition all --split dev --summary-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.action_validity import action_violation
from benchmark.repo_task_eval import CONDITIONS as REPO_CONDITIONS
from benchmark.repo_task_eval import (
    OLLAMA,
    append_row,
    corpus_hash,
    harness_hash,
    load_rows,
    model_digest,
    residency_snapshot,
    seed_workspace,
    unload_model,
)
from benchmark.repo_tasks import TASKS, RepoTask
from core.bounded_task import snapshot
from core.outcomes import EscalationRequired
from core.path_candidates import declared_paths, normalize
from core.repo_index import RepositoryIndex
from main import build_application

RESULTS = REPO_ROOT / "benchmark" / "results" / "localization_eval.jsonl"
RESIDENCY = REPO_ROOT / "benchmark" / "results" / "localization_eval_residency.jsonl"

LOCALIZE_TEMPLATE = (
    "Task: {prompt}\n\n"
    "Do not change any files. Only find the files and the functions or classes that would need to be inspected or "
    "changed to do this task. When you know, finish with "
    "{{\"tool\": \"done\", \"args\": {{\"summary\": \"FILES: <file paths>; SYMBOLS: <function or class names>\"}}}}."
)

# Optional repo tools are available in every level; the intervention is deterministic grounding (L1) and
# evidence-gated completion (L2), not tool availability.
_BASE = {"navigation_only": True, "repo_tools": True}
LEVELS = {
    "L0": {"targeted_grounding": False, "evidence_gated_completion": False},
    "L1": {"targeted_grounding": True, "evidence_gated_completion": False},
    "L2": {"targeted_grounding": True, "evidence_gated_completion": True},
}
CONDITIONS: dict[str, dict[str, Any]] = {}
for model_key, source in (("gemma", "gemma_constrained"), ("qwen", "qwen_constrained")):
    for level, flags in LEVELS.items():
        cfg = REPO_CONDITIONS[source]
        CONDITIONS[f"{model_key}_{level}"] = {"model": cfg["model"], "overrides": {**cfg["overrides"], **_BASE, **flags}}
_EVIDENCE_TOOLS = {"search_files", "repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone"}


def observed_evidence(timeline: list[tuple[str, dict[str, Any]]], workspace_files: set[str]) -> set[str]:
    """Paths established during the run, reconstructed from events independently of the loop's own bookkeeping."""
    evidence: set[str] = set()
    for etype, payload in timeline:
        if etype == "request.grounded":
            evidence |= {normalize(p) for p in payload.get("evidence", [])}
        elif etype == "tool.result" and payload.get("success"):
            tool = payload.get("tool") or payload.get("tool_name")
            if tool == "read_file":
                evidence.add(normalize(str((payload.get("arguments") or {}).get("path") or "")))
            elif tool in _EVIDENCE_TOOLS:
                evidence |= {normalize(p) for p in declared_paths(str(payload.get("result") or ""))}
    return {p for p in evidence if p in workspace_files}

_PATH_TOOLS = {"read_file": "path", "list_directory": "path", "find_tests": "target", "dependency_cone": "target"}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def gold_symbol_names(task: RepoTask) -> set[str]:
    return {s.rsplit(".", 1)[-1] for s in task.gold_symbols}


def parse_declaration(answer: str, index: RepositoryIndex) -> tuple[list[str], list[str]]:
    """Declared file paths and symbol simple names from the final answer."""
    files = list(dict.fromkeys(declared_paths(answer or "")))
    symbol_part = ""
    match = re.search(r"SYMBOLS\s*:\s*(.*)", answer or "", flags=re.IGNORECASE | re.DOTALL)
    if match:
        symbol_part = match.group(1)
    else:
        known = {s.name for info in index.modules.values() for s in info.symbols}
        symbol_part = " ".join(tok for tok in _IDENT.findall(answer or "") if tok.rsplit(".", 1)[-1] in known)
    names = []
    for token in _IDENT.findall(symbol_part):
        if token.endswith(".py") or "/" in token:
            continue
        simple = token.rsplit(".", 1)[-1]
        if simple.lower() in {"py", "none", "and", "or", "files", "symbols"}:
            continue
        names.append(simple)
    return files, list(dict.fromkeys(names))


def _looks_like_path(value: str) -> bool:
    return "/" in value or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", value))


def score_task(task: RepoTask, answer: str, timeline: list[tuple[str, dict[str, Any]]], workspace_files: set[str],
               index: RepositoryIndex, replies: list[str | None]) -> dict[str, Any]:
    gold_files = {normalize(g) for g in task.gold_files}
    gold_symbols = gold_symbol_names(task)
    declared_files, declared_symbols = parse_declaration(answer, index)
    known_symbols = {s.name for info in index.modules.values() for s in info.symbols}

    touched: list[str] = []
    path_calls = invented_paths = 0
    for etype, payload in timeline:
        if etype != "tool.invoked":
            continue
        tool, args = payload.get("tool_name"), payload.get("arguments") or {}
        key = _PATH_TOOLS.get(tool)
        value = args.get(key) if key else (args.get("name") if tool == "find_symbol" else None)
        if not isinstance(value, str) or not value.strip():
            continue
        if key is None and not _looks_like_path(value):
            continue
        if key in ("target",) and not _looks_like_path(value):
            continue
        path_calls += 1
        path = normalize(value)
        exists = path in workspace_files or (tool == "list_directory" and (path in ("", ".") or any(f.startswith(path + "/") for f in workspace_files)))
        if not exists:
            invented_paths += 1
        elif path in workspace_files and path not in touched:
            touched.append(path)

    def recall(hits: set[str], gold: set[str]) -> float | None:
        return round(len(hits & gold) / len(gold), 3) if gold else None

    def precision(declared: list[str], gold: set[str]) -> float | None:
        return round(len(set(declared) & gold) / len(set(declared)), 3) if declared else None

    evidence = observed_evidence(timeline, workspace_files)
    unsupported = [f for f in declared_files if f not in workspace_files or f not in evidence]
    first_gold = next((i for i, p in enumerate(touched) if p in gold_files), None)
    rejections = [p for t, p in timeline if t == "guard.rejected"]
    protocol_failures = sum(v is not None for v in replies) + sum(1 for p in rejections if p.get("reason") == "navigation_only")
    return {
        "declared_files": declared_files,
        "declared_symbols": declared_symbols,
        "declaration_present": bool(declared_files or declared_symbols),
        "file_recall": recall(set(declared_files), gold_files),
        "file_precision": precision(declared_files, gold_files),
        "symbol_recall": recall(set(declared_symbols), gold_symbols),
        "symbol_precision": precision(declared_symbols, gold_symbols) if gold_symbols else None,
        "declared_invented_files": [f for f in declared_files if f not in workspace_files],
        "unsupported_declared_files": unsupported,
        "grounded": any(t == "request.grounded" for t, _ in timeline),
        "done_rejections": sum(1 for t, p in timeline if t == "done.rejected" and p.get("reason") == "unsupported_declaration"),
        "declared_unknown_symbols": [s for s in declared_symbols if s not in known_symbols],
        "touched_files": touched,
        "touched_file_recall": recall(set(touched), gold_files),
        "touched_file_precision": precision(touched, gold_files),
        "first_gold_rank": first_gold,
        "path_calls": path_calls,
        "invented_path_calls": invented_paths,
        "model_replies": len(replies),
        "protocol_failures": protocol_failures,
        "write_attempts": sum(1 for p in rejections if p.get("reason") == "navigation_only"),
    }


def run_task(task: RepoTask, condition: str) -> dict[str, Any]:
    config = CONDITIONS[condition]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cordii-localize-") as tmp:
        workspace = seed_workspace(task, Path(tmp))
        before = snapshot(workspace)
        index = RepositoryIndex(workspace)
        workspace_files = set(index.files)
        ctx, reg = build_application(workspace, config["model"], OLLAMA, Path(tmp) / "loc.db", profile="lite", calibration_overrides=config["overrides"])
        model = ctx.plugins["ollama_model"]
        schema = getattr(model, "response_format", None)
        replies: list[str | None] = []
        prompt_tokens: list[int] = []
        original_chat = model.chat

        def recording_chat(messages, tools, _orig=original_chat, _model=model):
            reply = _orig(messages, tools)
            if tools and schema:
                replies.append(action_violation((reply.content or "").strip(), schema))
            usage = getattr(_model, "last_token_usage", None)
            if usage is not None:
                prompt_tokens.append(usage.prompt_eval_count)
            return reply

        model.chat = recording_chat
        timeline: list[tuple[str, dict[str, Any]]] = []
        ctx.events.on("*", lambda event: timeline.append((event.type, dict(event.payload or {}))))
        answer, escalation, error = "", None, None
        try:
            answer = str(ctx.plugins["agent_loop"].run(LOCALIZE_TEMPLATE.format(prompt=task.prompt)))
        except EscalationRequired as exc:
            escalation = exc.outcome.reason
        except Exception as exc:  # recorded with its cause; the task scores as no declaration
            error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            reg.stop_all()
        after = snapshot(workspace)
        scores = score_task(task, answer, timeline, workspace_files, index, replies)
    return {
        "task": task.name, "repo": task.repo, "split": task.split, "category": task.category, "condition": condition,
        "model": config["model"], "repo_tools": config["overrides"]["repo_tools"], "answer": answer[:600],
        "escalation": escalation, "error": error, "workspace_unchanged": before == after,
        "gold_files": list(task.gold_files), "gold_symbols": sorted(gold_symbol_names(task)),
        **scores,
        "tool_calls": sum(1 for t, _ in timeline if t == "tool.invoked"),
        "tools_used": sorted({p.get("tool_name") for t, p in timeline if t == "tool.invoked"}),
        "rounds": sum(1 for t, _ in timeline if t == "turn.round"),
        "prompt_tokens": sum(prompt_tokens),
        "seconds": round(time.perf_counter() - started, 1),
    }


def fingerprint(task: RepoTask, condition: str, digest: str, corpus: str, harness: str) -> str:
    payload = {"task": task.name, "condition": condition, "config": CONDITIONS[condition], "digest": digest, "corpus": corpus,
               "harness": harness, "template": LOCALIZE_TEMPLATE, "spec": asdict(task.public_spec),
               "source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(key: str) -> float | None:
        values = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    path_calls = sum(r["path_calls"] for r in rows)
    replies = sum(r["model_replies"] for r in rows)
    ranks = [r["first_gold_rank"] for r in rows if r["first_gold_rank"] is not None]
    return {
        "tasks": len(rows),
        "declarations": f"{sum(r['declaration_present'] for r in rows)}/{len(rows)}",
        "file_recall": mean("file_recall"),
        "file_precision": mean("file_precision"),
        "symbol_recall": mean("symbol_recall"),
        "symbol_precision": mean("symbol_precision"),
        "touched_file_recall": mean("touched_file_recall"),
        "touched_file_precision": mean("touched_file_precision"),
        "tasks_touching_gold": f"{len(ranks)}/{len(rows)}",
        "mean_first_gold_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "invented_path_rate": f"{sum(r['invented_path_calls'] for r in rows)}/{path_calls}",
        "unsupported_declaration_rate": f"{sum(len(r['unsupported_declared_files']) for r in rows)}/{sum(len(r['declared_files']) for r in rows)}",
        "evidence_gate_rejections": sum(r["done_rejections"] for r in rows),
        "escalation_reasons": {reason: sum(r["escalation"] == reason for r in rows) for reason in sorted({r["escalation"] for r in rows if r["escalation"]})},
        "protocol_failure_rate": f"{sum(r['protocol_failures'] for r in rows)}/{replies}",
        "write_attempts": sum(r["write_attempts"] for r in rows),
        "workspace_changed_tasks": sum(not r["workspace_unchanged"] for r in rows),
        "escalations": sum(r["escalation"] is not None for r in rows),
        "tool_calls": sum(r["tool_calls"] for r in rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Localization-only benchmark")
    parser.add_argument("--condition", choices=[*CONDITIONS, "all"], default="all")
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    results = Path(args.results)
    tasks = [t for t in TASKS if t.split == args.split and t.expected_outcome == "verified_done"]
    corpus, harness = corpus_hash(), harness_hash()
    summary: dict[str, Any] = {}
    for condition in (list(CONDITIONS) if args.condition == "all" else [args.condition]):
        model = CONDITIONS[condition]["model"]
        digest = model_digest(model)
        prints = {t.name: fingerprint(t, condition, digest, corpus, harness) for t in tasks}
        done = {r["task"] for r in load_rows(results) if r.get("condition") == condition and prints.get(r.get("task")) == r.get("fingerprint")}
        if not args.summary_only:
            append_row(RESIDENCY, residency_snapshot(condition, "before"))
            for task in tasks:
                if task.name in done:
                    continue
                row = run_task(task, condition)
                row["fingerprint"] = prints[task.name]
                append_row(results, row)
                print(json.dumps({k: row[k] for k in ("condition", "task", "declared_files", "file_recall", "file_precision", "invented_path_calls", "escalation")}), flush=True)
            append_row(RESIDENCY, residency_snapshot(condition, "after_run"))
            released = unload_model(model)
            append_row(RESIDENCY, {**residency_snapshot(condition, "after_unload"), "model_unloaded": released})
        latest = {}
        for row in load_rows(results):
            if row.get("condition") == condition and prints.get(row.get("task")) == row.get("fingerprint"):
                latest[row["task"]] = row
        summary[condition] = {"complete": len(latest) == len(tasks), **summarize(list(latest.values()))}
    print(json.dumps({"split": args.split, "conditions": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
