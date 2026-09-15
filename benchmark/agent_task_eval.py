"""End-to-end agent task eval through the production lite profile.

Each task seeds a temporary workspace, runs AgentLoop via main.build_application,
and checks the resulting files. Besides task success it records, per task:
proposal-level wrong-path errors (classified with the same rule as the path guard),
guard rejections with their outcome (repaired / repeated / unresolved), stray files,
rounds, tool calls, action validity, repeats and escalations.

The TASKS corpus is frozen for guard comparisons: change it only together with a new baseline.

Usage:
    python benchmark/agent_task_eval.py --model gemma3:1b --path-guard off --label baseline
    python benchmark/agent_task_eval.py --model gemma3:1b --path-guard on --label path_guard
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.action_validity import action_violation
from core.bounded_task import TaskSpec, run_bounded_task
from core.outcomes import EscalationRequired
from core.path_candidates import classify_path, normalize
from main import build_application

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _text(ws: Path, name: str) -> str:
    p = ws / name
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _json_port(ws: Path, name: str) -> dict:
    try:
        data = json.loads(_text(ws, name))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _python_ok(code: str, probe: str, expected: list[str]) -> bool:
    proc = subprocess.run([sys.executable, "-c", code + "\n" + probe], capture_output=True, text=True, timeout=10)
    return proc.returncode == 0 and proc.stdout.split() == expected


def _add_works(ws: Path, name: str) -> bool:
    return _python_ok(_text(ws, name), "print(add(2, 3), add(-1, 1))", ["5", "0"])


@dataclass(frozen=True)
class AgentTask:
    name: str
    prompt: str
    seed: dict[str, str]
    check: Callable[[Path], bool]
    expected_new: frozenset[str] = field(default_factory=frozenset)
    # Acceptable path(s) for the first file-tool proposal; None = not scored (e.g. multi-file deletes). Metadata only.
    first_paths: frozenset[str] | None = None
    # Files the answer must be derived from; a write before a successful read of one counts as an unread-source write.
    source_paths: frozenset[str] = field(default_factory=frozenset)


TASKS: list[AgentTask] = [
    AgentTask(
        "count_lines",
        "Read notes.txt, then write a file summary.txt containing only the number of lines in notes.txt.",
        {"notes.txt": "alpha\nbeta\ngamma\n"},
        lambda ws: _text(ws, "summary.txt").strip() == "3",
        frozenset({"summary.txt"}),
        frozenset({"notes.txt"}),
        frozenset({"notes.txt"}),
    ),
    AgentTask(
        "hello_script",
        "Create hello.py that prints Hello, World",
        {},
        lambda ws: "print" in _text(ws, "hello.py") and "Hello" in _text(ws, "hello.py"),
        frozenset({"hello.py"}),
        frozenset({"hello.py"}),
    ),
    AgentTask(
        "edit_config",
        "config.json sets port to 3000. Change the port to 8080 and keep the rest of the file.",
        {"config.json": '{"name": "demo", "port": 3000}'},
        lambda ws: _json_port(ws, "config.json").get("port") == 8080 and _json_port(ws, "config.json").get("name") == "demo",
        first_paths=frozenset({"config.json"}),
    ),
    AgentTask(
        "fix_bug",
        "Fix the bug in add.py: the add function subtracts instead of adding.",
        {"add.py": "def add(a, b):\n    return a - b\n"},
        lambda ws: _add_works(ws, "add.py"),
        first_paths=frozenset({"add.py"}),
    ),
    AgentTask(
        "delete_logs",
        "Delete every .log file in the project folder but keep other files.",
        {"a.log": "x", "b.log": "y", "keep.txt": "z"},
        lambda ws: not (ws / "a.log").exists() and not (ws / "b.log").exists() and (ws / "keep.txt").exists(),
    ),
    # Path-sensitive tasks: the file is not where the request's wording implies.
    AgentTask(
        "nested_fix_bug",
        "Fix the bug in add.py: the add function subtracts instead of adding.",
        {"src/mathlib/add.py": "def add(a, b):\n    return a - b\n"},
        lambda ws: _add_works(ws, "src/mathlib/add.py"),
        first_paths=frozenset({"src/mathlib/add.py"}),
    ),
    AgentTask(
        "nested_config_port",
        "app.json sets port to 3000. Change the port to 8080 and keep the rest of the file.",
        {"config/app.json": '{"name": "demo", "port": 3000}'},
        lambda ws: _json_port(ws, "config/app.json").get("port") == 8080 and _json_port(ws, "config/app.json").get("name") == "demo",
        first_paths=frozenset({"config/app.json"}),
    ),
    AgentTask(
        "nested_read_count",
        "Read notes.txt, then write a file count.txt containing only the number of lines in notes.txt.",
        {"docs/notes.txt": "alpha\nbeta\ngamma\n"},
        lambda ws: _text(ws, "count.txt").strip() == "3",
        frozenset({"count.txt"}),
        frozenset({"docs/notes.txt"}),
        frozenset({"docs/notes.txt"}),
    ),
    AgentTask(
        "nested_append",
        "Add a line saying bye to the end of greetings.txt.",
        {"messages/greetings.txt": "hello\n"},
        lambda ws: "hello" in _text(ws, "messages/greetings.txt") and "bye" in _text(ws, "messages/greetings.txt"),
        first_paths=frozenset({"messages/greetings.txt"}),
    ),
    # Control: same file name exists elsewhere, but the request names the full new path (must not be refused).
    AgentTask(
        "create_named_duplicate",
        "Create src/README.md with the line 'source code'.",
        {"docs/README.md": "documentation\n"},
        lambda ws: "source code" in _text(ws, "src/README.md") and _text(ws, "docs/README.md") == "documentation\n",
        frozenset({"src/README.md"}),
        frozenset({"src/README.md"}),
    ),
]


def _add_spec(path: str, instruction: str) -> TaskSpec:
    return TaskSpec(instruction, (path,), (
        {"type": "python_call_equals", "path": path, "expression": "print(add(2, 3), add(-1, 1))", "expected_stdout": "5 0"},
    ), allow_code_execution=True)


def _port_spec(path: str, instruction: str) -> TaskSpec:
    return TaskSpec(instruction, (path,), (
        {"type": "json_pointer_equals", "path": path, "pointer": "/port", "value": 8080},
        {"type": "json_keys_preserved", "path": path},
    ))


# Deterministic acceptance specs a coordinator would supply for the frozen corpus (bounded-lane evaluation).
# Built from the same prompts; checks are independent of the eval's own task.check lambdas.
LANE_SPECS: dict[str, Callable[[AgentTask], TaskSpec]] = {
    "count_lines": lambda t: TaskSpec(t.prompt, ("summary.txt",), ({"type": "file_equals", "path": "summary.txt", "text": "3"},)),
    "hello_script": lambda t: TaskSpec(t.prompt, ("hello.py",), (
        {"type": "file_contains", "path": "hello.py", "substrings": ["print", "Hello"]},
        {"type": "python_compiles", "path": "hello.py"},
    )),
    "edit_config": lambda t: _port_spec("config.json", t.prompt),
    "fix_bug": lambda t: _add_spec("add.py", t.prompt),
    "delete_logs": lambda t: TaskSpec(t.prompt, ("a.log", "b.log"), (
        {"type": "file_absent", "path": "a.log"},
        {"type": "file_absent", "path": "b.log"},
    )),
    "nested_fix_bug": lambda t: _add_spec("src/mathlib/add.py", t.prompt),
    "nested_config_port": lambda t: _port_spec("config/app.json", t.prompt),
    "nested_read_count": lambda t: TaskSpec(t.prompt, ("count.txt",), ({"type": "file_equals", "path": "count.txt", "text": "3"},)),
    "nested_append": lambda t: TaskSpec(t.prompt, ("messages/greetings.txt",), (
        {"type": "file_contains", "path": "messages/greetings.txt", "substrings": ["hello", "bye"]},
    )),
    "create_named_duplicate": lambda t: TaskSpec(t.prompt, ("src/README.md",), (
        {"type": "file_contains", "path": "src/README.md", "substrings": ["source code"]},
    )),
}


def _print_trace(ctx) -> None:
    el = ctx.plugins["event_logger"]
    for ev in el.event_log.get_session_events(el.continuity.session_id):
        if ev.type in ("assistant.message", "tool.result", "user.message", "system.message"):
            p = ev.payload or {}
            body = p.get("content") or p.get("result") or ""
            print(f"    {ev.type:18} {str(body)[:180]!r}")


def _files(ws: Path) -> set[str]:
    return {p.relative_to(ws).as_posix() for p in ws.rglob("*") if p.is_file()}


def rejection_outcomes(timeline: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """For each guard rejection: did the model repair it (a later successful call of the same tool on another path),
    repeat it (same path proposed again / repeat escalation), or leave it unresolved?"""
    outcomes = []
    for i, (etype, payload) in enumerate(timeline):
        if etype != "guard.rejected":
            continue
        tool, path = payload.get("tool"), normalize(str(payload.get("path") or ""))
        later = timeline[i + 1:]
        retried = any(t == "tool.invoked" and p.get("tool_name") == tool for t, p in later)
        # A wrong-path refusal is repaired only by a later successful call of the same tool on one of the offered
        # candidates; other refusals (e.g. unread_overwrite) by a later successful call of the same tool on the same path.
        if payload.get("reason") == "wrong_path":
            accepted = {normalize(c) for c in payload.get("candidates") or []}
        else:
            accepted = {path}
        repaired = any(
            t == "tool.result" and p.get("success") and p.get("tool") == tool
            and normalize(str((p.get("arguments") or {}).get("path") or "")) in accepted
            for t, p in later
        )
        repeated = any(
            (t == "guard.rejected" and p.get("reason") == payload.get("reason") and normalize(str(p.get("path") or "")) == path)
            or (t == "repeat.detected" and any(f'"path": "{path}"' in c for c in p.get("calls", [])))
            for t, p in later
        )
        outcome = "repaired" if repaired else "repeated" if repeated else "unresolved"
        outcomes.append({
            "reason": payload.get("reason"), "conflict": payload.get("conflict"), "tool": tool, "path": payload.get("path"),
            "candidates": payload.get("candidates"), "round": payload.get("round"), "retried": retried, "outcome": outcome,
        })
    return outcomes


_MUTATING = ("write_file", "replace_text", "patch_json", "delete_file")


def _json_keys(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        keys = set()
        for k, v in value.items():
            keys.add(f"{prefix}/{k}")
            keys |= _json_keys(v, f"{prefix}/{k}")
        return keys
    return set()


def _py_names(code: str) -> set[str] | None:
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def damaged_files(ws: Path, seed: dict[str, str]) -> list[str]:
    """Seeded files that still exist, changed, and lost original structure or content."""
    damaged = []
    for rel, original in seed.items():
        target = ws / rel
        if not target.is_file():
            continue
        final = target.read_text(encoding="utf-8", errors="replace")
        if final == original:
            continue
        if rel.endswith(".json"):
            try:
                ok = _json_keys(json.loads(original)) <= _json_keys(json.loads(final))
            except json.JSONDecodeError:
                ok = False
        elif rel.endswith(".py"):
            before, after = _py_names(original), _py_names(final)
            ok = after is not None and (before or set()) <= after
        else:
            final_lines = set(final.splitlines())
            ok = all(line in final_lines for line in original.splitlines() if line.strip())
        if not ok:
            damaged.append(rel)
    return damaged


def unread_source_writes(timeline: list[tuple[str, dict[str, Any]]], source_paths: frozenset[str]) -> int:
    """Successful mutations that happened before any successful read of a source file."""
    if not source_paths:
        return 0
    wanted = {normalize(p) for p in source_paths}
    count = 0
    for etype, payload in timeline:
        if etype != "tool.result" or not payload.get("success"):
            continue
        path = normalize(str((payload.get("arguments") or {}).get("path") or ""))
        if payload.get("tool") == "read_file" and path in wanted:
            return count
        if payload.get("tool") in _MUTATING:
            count += 1
    return count


def run_task(model_name: str, task: AgentTask, overrides: dict[str, Any], trace: bool = False, lane: bool = False) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        for rel, content in task.seed.items():
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_text(content, encoding="utf-8")
        seeded = _files(ws)
        ctx, reg = build_application(ws, model_name, "http://127.0.0.1:11434", Path(tmp) / "eval.db", profile="lite", calibration_overrides=overrides)
        model = ctx.plugins["ollama_model"]
        schema = getattr(model, "response_format", None)
        replies: list[str | None] = []
        prompt_tokens: list[int] = []
        original_chat = model.chat

        def checked_chat(messages, tools, _orig=original_chat, _model=model):
            reply = _orig(messages, tools)
            if tools and schema:
                replies.append(action_violation((reply.content or "").strip(), schema))
            usage = getattr(_model, "last_token_usage", None)
            if usage is not None:
                prompt_tokens.append(usage.prompt_eval_count)
            return reply

        model.chat = checked_chat
        timeline: list[tuple[str, dict[str, Any]]] = []
        proposals: list[dict[str, Any]] = []

        def on_event(event, _ws=ws, _request=task.prompt):
            payload = dict(event.payload or {})
            timeline.append((event.type, payload))
            if event.type == "tool.invoked":
                tool, args = payload.get("tool_name"), payload.get("arguments") or {}
                verdict = classify_path(_ws, str(tool), args.get("path") if isinstance(args.get("path"), str) else "", _request)
                proposals.append({"tool": tool, "path": args.get("path"), "wrong_path": verdict.wrong_path, "conflict": verdict.conflict})

        ctx.events.on("*", on_event)
        start = time.perf_counter()
        error = None
        escalation = None
        result = ""
        lane_result = None
        try:
            if lane:
                lane_result = run_bounded_task(LANE_SPECS[task.name](task), ws, ctx.plugins["agent_loop"].run)
                result = lane_result.agent_answer or ""
                escalation = lane_result.agent_escalation
                if lane_result.reason.startswith("agent failed"):
                    error = lane_result.reason
            else:
                result = str(ctx.plugins["agent_loop"].run(task.prompt))
        except EscalationRequired as exc:
            escalation = exc.outcome.to_dict()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if trace:
                _print_trace(ctx)
            reg.stop_all()
        stray = sorted(_files(ws) - seeded - set(task.expected_new))
        wrong = [p for p in proposals if p["wrong_path"]]
        counts = {t: sum(1 for et, _ in timeline if et == t) for t in ("turn.round", "repeat.detected", "model.resampled")}
        first_path = next((normalize(str(p["path"])) for p in proposals if p["tool"] in ("read_file", "write_file", "replace_text", "patch_json") and p["path"]), None)
        grounding = next((p for t, p in timeline if t == "request.grounded"), None)
        success = bool(task.check(ws))
        return {
            "task": task.name,
            "success": success,
            "lane_state": lane_result.state if lane_result else None,
            "lane_reason": lane_result.reason if lane_result else None,
            "lane_false_verified": bool(lane_result and lane_result.state == "verified_done" and not success),
            "false_done": not success and escalation is None and error is None,
            "first_path": first_path,
            "first_path_correct": None if task.first_paths is None else first_path in task.first_paths,
            "grounding": grounding["lines"] if grounding else None,
            "unread_source_writes": unread_source_writes(timeline, task.source_paths),
            "damaged_files": damaged_files(ws, task.seed),
            "edit_tools_used": sorted({p["tool"] for p in proposals if p["tool"] in ("replace_text", "patch_json")}),
            "prompt_tokens_total": sum(prompt_tokens),
            "prompt_tokens_first_call": prompt_tokens[0] if prompt_tokens else None,
            "rounds": counts["turn.round"],
            "tool_calls": len(proposals),
            "model_replies": len(replies),
            "invalid_actions": [v for v in replies if v is not None],
            "wrong_path_proposals": len(wrong),
            "wrong_path_by_conflict": {k: sum(1 for p in wrong if p["conflict"] == k) for k in ("exact_basename", "near_name") if any(p["conflict"] == k for p in wrong)},
            "guard_rejections": rejection_outcomes(timeline),
            "stray_files": stray,
            "repeats": counts["repeat.detected"],
            "resamples": counts["model.resampled"],
            "seconds": round(time.perf_counter() - start, 1),
            "result": result[:160],
            "error": error,
            "escalation": {k: escalation[k] for k in ("reason", "round", "repeated_calls")} if escalation else None,
        }


def summarize(model_name: str, label: str, overrides: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_replies = sum(r["model_replies"] for r in rows)
    invalid = sum(len(r["invalid_actions"]) for r in rows)
    rejections = [g for r in rows for g in r["guard_rejections"]]
    by_reason: dict[str, dict[str, int]] = {}
    for g in rejections:
        bucket = by_reason.setdefault(str(g["reason"]), {"total": 0, "repaired": 0, "repeated": 0, "unresolved": 0})
        bucket["total"] += 1
        bucket[g["outcome"]] += 1
    tasks_with_rejection = [r for r in rows if r["guard_rejections"]]
    return {
        "model": model_name,
        "label": label,
        "overrides": overrides,
        "tasks": len(rows),
        "success_rate": round(sum(r["success"] for r in rows) / len(rows), 3),
        "succeeded": [r["task"] for r in rows if r["success"]],
        "first_path_correct": f"{sum(1 for r in rows if r['first_path_correct'])}/{sum(1 for r in rows if r['first_path_correct'] is not None)}",
        "false_done": [r["task"] for r in rows if r["false_done"]],
        "lane_states": {s: [r["task"] for r in rows if r["lane_state"] == s] for s in ("verified_done", "proposal_complete", "escalate") if any(r["lane_state"] == s for r in rows)},
        "lane_false_verified": [r["task"] for r in rows if r["lane_false_verified"]],
        "lane_missed_success": [r["task"] for r in rows if r["lane_state"] and r["lane_state"] != "verified_done" and r["success"]],
        "unread_source_writes": {r["task"]: r["unread_source_writes"] for r in rows if r["unread_source_writes"]},
        "damaged_files": {r["task"]: r["damaged_files"] for r in rows if r["damaged_files"]},
        "tool_calls": sum(r["tool_calls"] for r in rows),
        "rounds": sum(r["rounds"] for r in rows),
        "prompt_tokens_total": sum(r["prompt_tokens_total"] for r in rows),
        "prompt_tokens_first_call": sum(r["prompt_tokens_first_call"] or 0 for r in rows),
        "wrong_path_proposals": sum(r["wrong_path_proposals"] for r in rows),
        "tasks_with_stray_files": [r["task"] for r in rows if r["stray_files"]],
        "guard_rejections_by_reason": by_reason,
        "recovered_after_guard_tasks": [r["task"] for r in tasks_with_rejection if r["success"]],
        "escalations": [r["task"] for r in rows if r["escalation"]],
        "model_replies": total_replies,
        "valid_action_rate": round((total_replies - invalid) / total_replies, 3) if total_replies else None,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="End-to-end agent task eval (lite profile)")
    p.add_argument("--model", default="gemma3:1b")
    p.add_argument("--task", action="append", help="Run only the named task (repeatable)")
    p.add_argument("--path-guard", choices=["preset", "on", "off"], default="preset", help="Override require_known_paths")
    p.add_argument("--grounding", choices=["preset", "on", "off"], default="preset", help="Override ground_request_paths")
    p.add_argument("--structured-edits", choices=["preset", "on", "off"], default="preset", help="Override structured_edits")
    p.add_argument("--lane", action="store_true", help="Run each task through the bounded lane with its deterministic acceptance spec")
    p.add_argument("--label", default=None, help="Save results to benchmark/results/agent_task_eval_<label>.json")
    p.add_argument("--trace", action="store_true", help="Print the conversation events for each task")
    args = p.parse_args()
    overrides: dict[str, Any] = {}
    if args.path_guard != "preset":
        overrides["require_known_paths"] = args.path_guard == "on"
    if args.grounding != "preset":
        overrides["ground_request_paths"] = args.grounding == "on"
    if args.structured_edits != "preset":
        overrides["structured_edits"] = args.structured_edits == "on"
    selected = [t for t in TASKS if not args.task or t.name in args.task]
    rows = []
    for t in selected:
        row = run_task(args.model, t, overrides, trace=args.trace, lane=args.lane)
        rows.append(row)
        print(json.dumps(row), flush=True)
    summary = summarize(args.model, args.label or "", overrides, rows)
    print(json.dumps(summary, indent=2))
    if args.label:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"agent_task_eval_{args.label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
