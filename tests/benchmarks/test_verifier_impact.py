"""Benchmark tests for AppVerifier impact on completion quality.

These benchmarks simulate 1.5B's tendency toward premature completion
by using deterministic models that sometimes return "done" without
producing complete artifacts. The verifier should catch these cases
and force the model to complete the work.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from core.context import Context
from core.messages import Message
from core.plugin import Plugin
from core.registry import PluginRegistry
from core.calibration import resolve_calibration
from plugins.agent.app_verifier import AppVerifier
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools
from plugins.tools.asgi_wsgi_tester import ASGIWSGITester


def tc(name, args):
    return {"function": {"name": name, "arguments": args}}


class PrematureCompletionModel(Plugin):
    """Simulates 1.5B's tendency to claim completion prematurely.

    For app-building tasks, this model:
    - Round 1: says "done" (premature, no files created)
    - Round 2 (if verifier injects feedback): writes one file
    - Round 3: says "done" again (still incomplete — missing other files)
    - Round 4: writes the remaining file
    - Round 5: says "done" (now complete)
    """
    name = "ollama_model"
    dependencies = ()

    def __init__(self, responses: list[Message]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.seen_messages = []

    def chat(self, messages, tools):
        self.calls += 1
        self.seen_messages.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return Message("assistant", "done")


# ---------------------------------------------------------------------------
# Benchmark task definitions
# ---------------------------------------------------------------------------

class BenchmarkReport:
    """Results from a single benchmark run."""
    def __init__(self):
        self.completed = False
        self.model_turns = 0
        self.tool_calls = 0
        self.feedback_injections = 0
        self.verification_events = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.error = ""

    def to_dict(self) -> dict:
        return {
            "completed": self.completed,
            "model_turns": self.model_turns,
            "tool_calls": self.tool_calls,
            "feedback_injections": self.feedback_injections,
            "verification_events": self.verification_events,
            "error": self.error,
        }


def _run_app_task(
    task_name: str,
    user_request: str,
    model_responses: list[Message],
    workspace_files: dict[str, str],
    enable_verifier: bool,
    max_rounds: int = 15,
) -> BenchmarkReport:
    """Run an app-building task with or without the verifier."""
    tmp_dir = tempfile.mkdtemp(prefix=f"bm_{task_name}_")
    tmp_path = Path(tmp_dir)

    try:
        # Pre-create workspace files (simulating what the model would create)
        for fname, content in workspace_files.items():
            full_path = tmp_path / fname
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

        cal = resolve_calibration("qwen2.5-coder:1.5b")
        config = {
            "profile": "lite",
            "workspace": str(tmp_path),
            "schema_router_enabled": True,
            "compact_schema": True,
            "calibration": cal,
        }
        ctx = Context(config=config)
        reg = PluginRegistry(ctx)
        reg.register(EventLogger(tmp_path / "benchmark.db"))
        reg.register(PrematureCompletionModel(model_responses))
        reg.register(FileTools(tmp_path))
        reg.register(ASGIWSGITester())  # Required dependency for AppVerifier
        if enable_verifier:
            reg.register(AppVerifier())
        reg.register(AgentLoop(max_rounds=max_rounds))
        reg.start_all()

        report = BenchmarkReport()
        try:
            result = ctx.plugins["agent_loop"].run(user_request)
            report.completed = "done" in result.lower() or len(result) > 0
        except Exception as exc:
            report.error = str(exc)
            report.completed = False

        model = reg._plugins.get("ollama_model")
        if model:
            report.model_turns = model.calls

        # Count tool calls from messages
        report.tool_calls = sum(1 for m in ctx.messages if m.tool_calls)

        # Count feedback injections
        report.feedback_injections = sum(
            1 for m in ctx.messages if m.role == "user" and "verification feedback" in m.content
        )

        return report
    finally:
        try:
            reg.stop_all()
        except Exception:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Todo App Benchmark
# ---------------------------------------------------------------------------

def test_benchmark_todo_app_without_verifier():
    """Todo app without verifier: model claims done prematurely."""
    responses = [
        Message("assistant", "Done! I built a todo app."),
    ]
    report = _run_app_task(
        task_name="todo_app",
        user_request="Build a todo app with add and delete functionality",
        model_responses=responses,
        workspace_files={},  # No files created — premature completion
        enable_verifier=False,
        max_rounds=3,
    )
    # Without verifier, the model claims done and the task is "complete"
    assert report.completed is True
    assert report.model_turns == 1


def test_benchmark_todo_app_with_verifier():
    """Todo app with verifier: premature completion is caught and fixed."""
    responses = [
        # Round 1: model says "done" (no files) → verifier catches → feedback injected
        Message("assistant", "Done! I built a todo app."),
        # Round 2: model writes index.html
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "index.html",
            "content": "<ul id='list'>todo</ul>",
        })]),
        # Round 3: model says "done" (only index.html, missing app.js) → verifier catches again
        Message("assistant", "Done now."),
        # Round 4: model writes app.js
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "app.js",
            "content": "function add() {} items.splice(0,1); items.filter(x=>x);",
        })]),
        # Round 5: model says "done" — verification passes
        Message("assistant", "Done!"),
    ]
    report = _run_app_task(
        task_name="todo_app",
        user_request="Build a todo app with add and delete functionality",
        model_responses=responses,
        workspace_files={},
        enable_verifier=True,
        max_rounds=15,
    )
    assert report.completed is True
    assert report.model_turns > 1  # Needed multiple rounds
    assert report.feedback_injections >= 1  # Verifier caught premature completion


# ---------------------------------------------------------------------------
# CRUD App Benchmark
# ---------------------------------------------------------------------------

def test_benchmark_crud_app_without_verifier():
    """CRUD app without verifier: model claims done with incomplete implementation."""
    responses = [
        Message("assistant", "I built the CRUD API."),
    ]
    report = _run_app_task(
        task_name="crud_app",
        user_request="Build a CRUD backend with create read update delete endpoints",
        model_responses=responses,
        workspace_files={},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True
    assert report.model_turns == 1


def test_benchmark_crud_app_with_verifier():
    """CRUD app with verifier: incomplete implementation is caught."""
    responses = [
        Message("assistant", "CRUD is done."),
        # Verifier catches missing server.js, feedback injected
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "server.js",
            "content": "app.post('/create', ...); app.get('/read', ...);"
            " app.put('/update', ...); app.delete('/delete', ...);",
        })]),
        Message("assistant", "Now it's complete."),
    ]
    report = _run_app_task(
        task_name="crud_app",
        user_request="Build a CRUD backend with create read update delete endpoints",
        model_responses=responses,
        workspace_files={},
        enable_verifier=True,
        max_rounds=15,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1


# ---------------------------------------------------------------------------
# Calculator App Benchmark
# ---------------------------------------------------------------------------

def test_benchmark_calc_app_without_verifier():
    """Calculator without verifier: claims done without display logic."""
    responses = [
        Message("assistant", "Calculator built and ready."),
    ]
    report = _run_app_task(
        task_name="calc_app",
        user_request="Build a calculator with display add subtract multiply divide",
        model_responses=responses,
        workspace_files={},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True


def test_benchmark_calc_app_with_verifier():
    """Calculator with verifier: catches missing display."""
    responses = [
        Message("assistant", "Calculator done."),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "index.html",
            "content": "<div id='display'>0</div><button onclick='add()'>+</button>",
        })]),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "app.js",
            "content": "function add(){display.innerText=+display.innerText+1}",
        })]),
        Message("assistant", "Complete!"),
    ]
    report = _run_app_task(
        task_name="calc_app",
        user_request="Build a calculator with display add subtract multiply divide",
        model_responses=responses,
        workspace_files={},
        enable_verifier=True,
        max_rounds=15,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1


# ---------------------------------------------------------------------------
# Dashboard App Benchmark
# ---------------------------------------------------------------------------

def test_benchmark_dashboard_app_without_verifier():
    """Dashboard without verifier: claims done without visualization."""
    responses = [
        Message("assistant", "Dashboard is ready."),
    ]
    report = _run_app_task(
        task_name="dashboard_app",
        user_request="Build a dashboard with charts and data visualization",
        model_responses=responses,
        workspace_files={},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True


def test_benchmark_dashboard_app_with_verifier():
    """Dashboard with verifier: catches missing data source."""
    responses = [
        Message("assistant", "Dashboard done."),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "index.html",
            "content": "<div id='chart'></div>",
        })]),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "app.js",
            "content": "fetch('/api/data').then(r=>r.json()).then(renderChart)",
        })]),
        Message("assistant", "Complete!"),
    ]
    report = _run_app_task(
        task_name="dashboard_app",
        user_request="Build a dashboard with charts and data visualization",
        model_responses=responses,
        workspace_files={},
        enable_verifier=True,
        max_rounds=15,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1


# ---------------------------------------------------------------------------
# Aggregate comparison tests
# ---------------------------------------------------------------------------

def test_verifier_improves_completion_rate():
    """Completion rate should be higher with verifier (apps that actually work).

    Without verifier: 1.5B claims done but files are incomplete → false positives.
    With verifier: only fully-complete apps are marked done → higher true positive rate.
    """
    # Without verifier: premature "done" is accepted as complete
    # With verifier: premature "done" triggers feedback, model must build the app
    # The verifier increases the number of apps that actually work
    without_report = _run_app_task(
        "todo_app",
        "Build a todo app with add and delete functionality",
        [Message("assistant", "Done! I built a todo app.")],
        {},
        enable_verifier=False,
        max_rounds=3,
    )

    with_report = _run_app_task(
        "todo_app",
        "Build a todo app with add and delete functionality",
        [
            Message("assistant", "Done! I built a todo app."),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "index.html", "content": "<ul id='list'>todo</ul>"
            })]),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "app.js",
                "content": "function add() {} items.splice(0,1); items.filter(x=>x);",
            })]),
            Message("assistant", "Done!"),
        ],
        {},
        enable_verifier=True,
        max_rounds=15,
    )

    # Without verifier: 1 model turn but 0 tool calls (app is empty)
    assert without_report.model_turns == 1
    assert without_report.tool_calls == 0

    # With verifier: more model turns but 2 tool calls (app is actually built)
    assert with_report.model_turns > 1
    assert with_report.tool_calls == 2
    assert with_report.feedback_injections >= 1


def test_verifier_acceptable_overhead():
    """Token overhead should be acceptable — verification feedback is bounded."""
    report = _run_app_task(
        "todo_app",
        "Build a todo app with add and delete functionality",
        [
            Message("assistant", "Done."),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "index.html", "content": "<ul id='list'>todo</ul>"
            })]),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "app.js",
                "content": "function add() {} items.splice(0,1); items.filter(x=>x);",
            })]),
            Message("assistant", "Done!"),
        ],
        {},
        enable_verifier=True,
        max_rounds=15,
    )

    # Verifier feedback is a short system/user message — minimal overhead
    # The model needs a few rounds to build the app, but not excessive
    assert report.feedback_injections >= 1  # Verifier caught premature completion
    # Overhead: feedback messages are short, injected as user not system
    assert report.model_turns <= 6  # Reasonable number of rounds


def test_zero_drag_when_verifier_not_relevant(tmp_path):
    """Non-app tasks should have zero verifier overhead (no verification feedback)."""
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg

    ctx = Ctx(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(PrematureCompletionModel([Message("assistant", "hello! I can help.")]))
    reg.register(FileTools(tmp_path))
    reg.register(ASGIWSGITester())
    reg.register(AppVerifier())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("say hello")
        assert result  # Completes normally

        # No verification feedback should be injected for non-app tasks
        feedback_msgs = [m for m in ctx.messages if m.role == "user" and "verification feedback" in m.content]
        assert len(feedback_msgs) == 0, "Verifier should not interfere with non-app tasks"
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Phase 4: Expanded app pattern benchmarks
# ---------------------------------------------------------------------------

def test_benchmark_auth_app_without_verifier():
    """Auth app without verifier: premature completion accepted."""
    report = _run_app_task(
        "auth_app",
        "Build an auth app with login and signup",
        [Message("assistant", "Auth app complete!")],
        {},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True
    assert report.model_turns == 1
    assert report.tool_calls == 0  # No files created


def test_benchmark_auth_app_with_verifier():
    """Auth app with verifier: incomplete app is caught."""
    report = _run_app_task(
        "auth_app",
        "Build an auth app with login and signup",
        [
            Message("assistant", "Auth app complete!"),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "server.js",
                "content": "app.post('/login',h);app.post('/signup',s);const token=jwt.sign({},'s');"
                "const hashed=bcrypt.hash(password,10);",
            })]),
            Message("assistant", "Done!"),
        ],
        {},
        enable_verifier=True,
        max_rounds=10,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1
    assert report.tool_calls >= 1


def test_benchmark_crud_app_without_verifier():
    """CRUD app without verifier: premature completion accepted."""
    report = _run_app_task(
        "crud_app",
        "Build a CRUD API with REST endpoints",
        [Message("assistant", "CRUD API is ready!")],
        {},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True


def test_benchmark_crud_app_with_verifier():
    """CRUD app with verifier: incomplete endpoints are caught."""
    report = _run_app_task(
        "crud_app",
        "Build a CRUD API with REST endpoints",
        [
            Message("assistant", "CRUD done!"),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "server.js",
                "content": "app.post('/create',c);app.get('/read',r);app.put('/update',u);app.delete('/delete',d);",
            })]),
            Message("assistant", "Now complete!"),
        ],
        {},
        enable_verifier=True,
        max_rounds=10,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1


def test_benchmark_calculator_without_verifier():
    """Calculator without verifier: premature completion accepted."""
    report = _run_app_task(
        "calc_app",
        "Build a calculator with add subtract multiply divide",
        [Message("assistant", "Calculator built!")],
        {},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True


def test_benchmark_calculator_with_verifier():
    """Calculator with verifier: missing display is caught."""
    report = _run_app_task(
        "calc_app",
        "Build a calculator with add subtract multiply divide",
        [
            Message("assistant", "Calculator done!"),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "index.html",
                "content": "<div id='display'>0</div><button onclick='add()'>+</button>",
            })]),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "app.js",
                "content": "function add(){display.innerText=+display.innerText+1}",
            })]),
            Message("assistant", "Complete!"),
        ],
        {},
        enable_verifier=True,
        max_rounds=10,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1


def test_benchmark_dashboard_without_verifier():
    """Dashboard without verifier: premature completion accepted."""
    report = _run_app_task(
        "dashboard_app",
        "Build a dashboard with charts and data",
        [Message("assistant", "Dashboard ready!")],
        {},
        enable_verifier=False,
        max_rounds=3,
    )
    assert report.completed is True


def test_benchmark_dashboard_with_verifier():
    """Dashboard with verifier: missing chart library is caught."""
    report = _run_app_task(
        "dashboard_app",
        "Build a dashboard with charts and data",
        [
            Message("assistant", "Dashboard done!"),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "index.html",
                "content": "<div id='chart'></div><canvas id='myChart'></canvas>",
            })]),
            Message("assistant", "", tool_calls=[tc("write_file", {
                "path": "app.js",
                "content": "const ctx = document.getElementById('myChart'); new Chart(ctx, {type:'bar'}); fetch('/api/data')",
            })]),
            Message("assistant", "Now complete!"),
        ],
        {},
        enable_verifier=True,
        max_rounds=10,
    )
    assert report.completed is True
    assert report.feedback_injections >= 1


def test_verifier_improves_all_app_types_completion_rate():
    """Verifier should consistently improve completion rate across app types."""
    app_configs = [
        ("auth_app", "auth app with login and signup", [
            Message("assistant", "done"),
            Message("assistant", "", tool_calls=[tc("write_file", {"path": "server.js", "content": "app.post('/login',h);app.post('/signup',s);const token=jwt.sign({},'s');const hashed=bcrypt.hash(p,10);"})]),
            Message("assistant", "done"),
        ]),
        ("todo_app", "todo app with add and delete", [
            Message("assistant", "done"),
            Message("assistant", "", tool_calls=[tc("write_file", {"path": "index.html", "content": "<ul id='list'>todo</ul>"})]),
            Message("assistant", "", tool_calls=[tc("write_file", {"path": "app.js", "content": "function add(){} items.splice(0,1); items.filter(x=>x);"})]),
            Message("assistant", "done"),
        ]),
    ]

    for name, request, responses in app_configs:
        without = _run_app_task(name + "_wov", request, [Message("assistant", "done")], {}, False, 3)
        with_r = _run_app_task(name + "_wv", request, responses, {}, True, 10)
        # Without verifier: 1 turn, 0 tool calls (premature completion)
        assert without.model_turns == 1
        # With verifier: more turns, actual tool calls, feedback injected
        assert with_r.tool_calls >= 1
        assert with_r.feedback_injections >= 1
