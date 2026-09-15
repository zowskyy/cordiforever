"""Single-turn action eval (checkpointed, resumable).

Sends the production system prompt plus one user request to a real Ollama model
and classifies the reply. Every sample is appended to a JSONL file as soon as it
finishes; re-running with the same configuration skips samples already recorded,
so an interrupted run (OOM, timeout, Ctrl+C) loses at most the sample in flight.

Dev tasks are scored semantically (category per sample). Emission probes are
scored only for "exactly one executable action" and are never used for tuning.

Usage:
    python benchmark/tool_call_eval.py --model gemma3:1b --temperature 0 --constrain --num-predict 2048
    python benchmark/tool_call_eval.py ... --samples 3 --max-new 30     # bounded batch; repeat to resume
    python benchmark/tool_call_eval.py ... --summary-only               # summarize what is recorded
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.action_validity import action_violation
from core.errors import ModelError
from core.messages import Message
from core.tool_call_extraction import extract_tool_calls_from_text
from plugins.agent.loop import LITE_COMPACT_GUIDANCE
from plugins.agent.schema_router import SchemaRouter
from plugins.model.ollama import OllamaModel

DEFAULT_OUT = Path(__file__).resolve().parent / "results" / "tool_call_eval.jsonl"

# Semantic categories, most specific first. Single-turn probes cannot observe sequencing,
# unnecessary actions or stale writes; those need multi-step traces.
SEMANTIC_CATEGORIES = (
    "ok",
    "wrong_tool",
    "wrong_path",
    "wrong_content",
    "premature_done",
    "missing_prerequisite_read",
    "invalid_action",
    "truncated",
    "model_error",
)


@dataclass(frozen=True)
class Task:
    prompt: str
    tools: tuple[str, ...]
    path: str | None
    content_check: Callable[[str], bool] | None = None
    modifies_existing: bool = False


TASKS: list[Task] = [
    Task("Read config.json", ("read_file",), "config.json"),
    Task("Show me what's in src/main.py", ("read_file",), "src/main.py"),
    Task("Fix the bug in app.py", ("read_file",), "app.py", modifies_existing=True),
    Task("Create hello.py that prints hello", ("write_file",), "hello.py", lambda c: "print" in c),
    Task("Write a README.md with the title My Project", ("write_file",), "README.md", lambda c: "My Project" in c),
    Task("Create requirements.txt containing requests", ("write_file",), "requirements.txt", lambda c: "requests" in c),
    Task("List the files in the workspace", ("list_directory",), None),
    Task("What files are in the tests folder?", ("list_directory",), "tests"),
    Task("Delete old.log", ("delete_file",), "old.log"),
    Task("Add a function add(a, b) to math_utils.py", ("read_file", "write_file"), "math_utils.py"),
    Task("Open package.json", ("read_file",), "package.json"),
    Task("Why does server.js crash on startup?", ("read_file",), "server.js"),
    Task("Explain what lib/parser.py does", ("read_file",), "lib/parser.py"),
    Task("Check the contents of .env.example", ("read_file",), ".env.example"),
    Task("Refactor utils/strings.py to use f-strings", ("read_file",), "utils/strings.py", modifies_existing=True),
    Task("Look at docs/setup.md and tell me the install steps", ("read_file",), "docs/setup.md"),
    Task("Create index.html with an h1 that says Welcome", ("write_file",), "index.html", lambda c: "Welcome" in c and "h1" in c),
    Task("Make a .gitignore that ignores node_modules", ("write_file",), ".gitignore", lambda c: "node_modules" in c),
    Task("Write test_math.py with a pytest test that asserts 1 + 1 == 2", ("write_file",), "test_math.py", lambda c: "assert" in c),
    Task("Create a file notes.txt containing: buy milk", ("write_file",), "notes.txt", lambda c: "buy milk" in c),
    Task("Save a JSON file settings.json with debug set to true", ("write_file",), "settings.json", lambda c: "debug" in c and "true" in c),
    Task("Generate a Python script fizzbuzz.py", ("write_file",), "fizzbuzz.py", lambda c: "Fizz" in c or "fizz" in c),
    Task("Show the project structure", ("list_directory",), None),
    Task("What's inside the src directory?", ("list_directory",), "src"),
    Task("List everything under assets/images", ("list_directory",), "assets/images"),
    Task("Which files exist in the root folder?", ("list_directory",), None),
    Task("Remove temp.txt", ("delete_file",), "temp.txt"),
    Task("Get rid of the file build/output.bin", ("delete_file",), "build/output.bin"),
    Task("Rename the variable x to count in counter.py", ("read_file",), "counter.py", modifies_existing=True),
    Task("Add error handling to fetch.js", ("read_file",), "fetch.js", modifies_existing=True),
]


# Emission probes: only "did it emit one executable action" is scored, never which one. Not used for tuning.
EMISSION_PROBES: list[str] = [
    "hey",
    "thanks, that's all for now",
    "can you help me with my project?",
    "what do you think of this codebase",
    "Make it better",
    "Undo that",
    "I need a login page and also fix the tests",
    "Is there a Dockerfile here?",
    "Please don't change anything, just look around",
    "Write the docs",
    "run the tests",
    "Why is it slow?",
    "Summarize what you did",
    "Create three files: a.txt, b.txt and c.txt",
    "Move main.py into src/",
    "Search for TODO comments",
    "ok",
    "What's 2+2?",
    "Translate README.md into Spanish",
    "Set up a Python virtual environment",
]


def _norm_path(p: Any) -> str:
    return str(p or "").strip().replace("\\", "/").removeprefix("./").rstrip("/")


def build_router() -> SchemaRouter:
    router = SchemaRouter()
    router.enabled = True
    router.compact_mode = True
    return router


def classify(task: Task, raw: str, router: SchemaRouter, tools: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (category, detail) for one dev-task reply."""
    calls = extract_tool_calls_from_text(raw, tools)
    if not calls:
        return "invalid_action", "no_tool_call"
    if router.done_summary(calls) is not None:
        return "premature_done", ""
    expanded = router.expand_call(calls[0])
    if expanded is None:
        return "invalid_action", "unexpandable"
    fn = expanded.get("function", {})
    name = fn.get("name")
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return "invalid_action", "bad_args_json"
    if name not in task.tools:
        if task.modifies_existing and name == "write_file":
            return "missing_prerequisite_read", f"path={args.get('path')!r}"
        return "wrong_tool", str(name)
    if task.path is None and name == "list_directory" and _norm_path(args.get("path")) not in ("", "."):
        return "wrong_path", repr(args.get("path"))
    if task.path is not None and _norm_path(args.get("path")) != _norm_path(task.path):
        return "wrong_path", repr(args.get("path"))
    if name == "write_file" and task.content_check is not None and not task.content_check(str(args.get("content", ""))):
        return "wrong_content", ""
    return "ok", ""


def config_key(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def load_rows(out: Path, key: str) -> list[dict[str, Any]]:
    if not out.is_file():
        return []
    rows = []
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a partially written last line from a killed process
        if row.get("config_key") == key:
            rows.append(row)
    return rows


def run(config: dict[str, Any], system_prompt: str, samples: int, out: Path, max_new: int | None, include_probes: bool) -> int:
    key = config_key(config)
    done = {(r["group"], r["prompt"], r["sample"]) for r in load_rows(out, key)}
    router = build_router()
    tools = router.get_model_tools()
    schema = router.get_response_format()
    model = OllamaModel(model=config["model"], options=config["options"], response_format=schema if config["constrain"] else None)
    system = json.dumps({"role": "system", "content": system_prompt}, ensure_ascii=False)
    work: list[tuple[str, str, Task | None, int]] = [("dev", t.prompt, t, i) for t in TASKS for i in range(samples)]
    if include_probes:
        work += [("probe", p, None, i) for p in EMISSION_PROBES for i in range(samples)]
    all_pending = [w for w in work if (w[0], w[1], w[3]) not in done]
    pending = all_pending[:max_new] if max_new is not None else all_pending
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    # A process killed mid-write leaves a partial last line; start on a fresh line so the next row survives.
    needs_newline = out.is_file() and out.stat().st_size > 0 and not out.read_bytes().endswith(b"\n")
    with out.open("a", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        for group, prompt, task, sample in pending:
            start = time.perf_counter()
            raw, tokens, done_reason = "", None, None
            try:
                reply = model.chat([Message(role="system", content=system), Message(role="user", content=prompt)], tools)
                raw = reply.content or ""
                if reply.tool_calls and not raw.strip():
                    raw = json.dumps({"tool_calls": reply.tool_calls})
                tokens = model.last_token_usage.eval_count if model.last_token_usage else None
                done_reason = model.last_done_reason
                if done_reason == "length":
                    category, detail = "truncated", ""
                elif config["constrain"] and (violation := action_violation(raw.strip(), schema)) is not None:
                    category, detail = "invalid_action", violation
                elif task is None:
                    category, detail = "ok", ""
                else:
                    category, detail = classify(task, raw, router, tools)
            except ModelError as exc:
                category, detail = "model_error", "timeout" if "timed out" in str(exc) else str(exc)[:200]
            row = {
                "config_key": key, "config": config, "group": group, "prompt": prompt, "sample": sample,
                "category": category, "detail": detail, "raw": raw[:2000], "output_tokens": tokens,
                "done_reason": done_reason, "seconds": round(time.perf_counter() - start, 2), "ts": time.time(),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            written += 1
    remaining = len(all_pending) - written
    print(f"[eval] wrote {written} new samples, {remaining} still pending -> {out}", file=sys.stderr)
    return remaining


def summarize(rows: list[dict[str, Any]], expected: dict[str, int]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for group in ("dev", "probe"):
        subset = [r for r in rows if r["group"] == group]
        if not subset:
            continue
        counts = {c: 0 for c in SEMANTIC_CATEGORIES}
        for r in subset:
            counts[r["category"]] = counts.get(r["category"], 0) + 1
        n = len(subset)
        executable = n - counts["invalid_action"] - counts["truncated"] - counts["model_error"]
        report[group] = {
            "n": n,
            "expected_n": expected[group],
            "complete": n >= expected[group],
            "executable_action_rate": round(executable / n, 3),
            **({"semantic_accuracy": round(counts["ok"] / n, 3)} if group == "dev" else {}),
            "categories": {c: v for c, v in counts.items() if v and (group == "dev" or c != "ok")},
        }
        tokens = [r["output_tokens"] for r in subset if r.get("output_tokens") is not None]
        report[group]["max_output_tokens"] = max(tokens) if tokens else None
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Checkpointed single-turn action eval")
    p.add_argument("--model", default="gemma3:1b")
    p.add_argument("--samples", type=int, default=1)
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--num-predict", type=int, default=None, help="Output token cap (production gemma preset uses 2048)")
    p.add_argument("--prompt-file", default=None, help="Evaluate a candidate system prompt instead of the production one")
    p.add_argument("--constrain", action="store_true", help="Constrain decoding to the compact action JSON schema")
    p.add_argument("--probes", action="store_true", help="Also run emission probes (scored for executable action only)")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="JSONL checkpoint file")
    p.add_argument("--max-new", type=int, default=None, help="Stop after this many new samples (resume by re-running)")
    p.add_argument("--summary-only", action="store_true")
    p.add_argument("--show", type=int, default=5, help="Print this many non-ok dev samples")
    args = p.parse_args()

    options: dict[str, Any] = {}
    if args.temperature is not None:
        options["temperature"] = args.temperature
    if args.num_predict is not None:
        options["num_predict"] = args.num_predict
    system_prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else LITE_COMPACT_GUIDANCE
    config = {
        "model": args.model,
        "options": options or None,
        "constrain": args.constrain,
        "prompt_sha": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16],
        "schema_sha": config_key(build_router().get_response_format() or {}),
        "tasks_sha": config_key({"tasks": [t.prompt for t in TASKS], "probes": EMISSION_PROBES}),
        "samples": args.samples,
    }
    out = Path(args.out)
    remaining = 0
    if not args.summary_only:
        remaining = run(config, system_prompt, args.samples, out, args.max_new, args.probes)
    rows = load_rows(out, config_key(config))
    expected = {"dev": len(TASKS) * args.samples, "probe": len(EMISSION_PROBES) * args.samples if args.probes else 0}
    print(json.dumps({"config_key": config_key(config), "config": config, "remaining": remaining, **summarize(rows, expected)}, indent=2))
    for r in [r for r in rows if r["group"] == "dev" and r["category"] != "ok"][: args.show]:
        print(f"--- [{r['category']}] {r['detail']} :: {r['prompt']}\n{r['raw'][:300]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
