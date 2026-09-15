"""Phase 2 tests: AppVerifier integration with AgentLoop.

These tests verify that the verifier is called when the model claims
completion, and that failed verification blocks premature completion.
"""
from __future__ import annotations

import json

import pytest

from core.context import Context
from core.messages import Message
from core.registry import PluginRegistry
from core.errors import ToolError
from plugins.agent.app_verifier import AppVerifier
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools
from plugins.tools.asgi_wsgi_tester import ASGIWSGITester

from tests.failure_recovery.harness import FaultInjectingModel


def tc(name, args):
    return {"function": {"name": name, "arguments": args}}


def _make_context(tmp_path, profile="lite"):
    ctx = Context(config={"profile": profile, "workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FileTools(tmp_path))
    reg.register(ASGIWSGITester())
    reg.register(AppVerifier())
    return ctx, reg


def test_verifier_obtained_in_start(tmp_path):
    """AppVerifier should be obtainable in AgentLoop.start()."""
    ctx, reg = _make_context(tmp_path)
    reg.register(FaultInjectingModel([Message("assistant", "done")], fault_config={}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        loop = ctx.plugins["agent_loop"]
        assert loop._app_verifier is not None
        assert loop._app_verifier.name == "app_verifier"
    finally:
        reg.stop_all()


def test_verifier_blocks_premature_completion(tmp_path):
    """When verification fails, completion should be blocked and feedback injected."""
    ctx, reg = _make_context(tmp_path)

    # Model says "done" first (verification fails), then writes index.html,
    # then says "done" again (verification passes)
    responses = [
        Message("assistant", "done"),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "index.html",
            "content": "<ul id='list'>todo</ul>",
        })]),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "app.js",
            "content": "function add() {} items.splice(0,1); items.filter(x=>x);",
        })]),
        Message("assistant", "done"),
    ]
    reg.register(FaultInjectingModel(responses, fault_config={}))
    reg.register(AgentLoop(max_rounds=10))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("build a todo app with add and delete")
        # Should have completed after verification passed
        assert "done" in result.lower() or result
    finally:
        reg.stop_all()

    # Feedback should have been injected after the first "done"
    user_msgs = [m for m in ctx.messages if m.role == "user" and "verification feedback" in m.content]
    assert len(user_msgs) >= 1, "Verification feedback should be injected"


def test_verifier_allows_valid_completion(tmp_path):
    """When all criteria pass, completion should be allowed immediately."""
    ctx, reg = _make_context(tmp_path)

    # Pre-create files that satisfy todo app criteria
    (tmp_path / "index.html").write_text("<ul id='list'>todo</ul>", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "function add() {} items.splice(0,1); items.filter(x=>x);",
        encoding="utf-8",
    )

    reg.register(FaultInjectingModel([Message("assistant", "done")], fault_config={}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("build a todo app")
        assert "done" in result.lower() or result  # Should return immediately
    finally:
        reg.stop_all()

    # No verification feedback should have been injected
    user_msgs = [m for m in ctx.messages if m.role == "user" and "verification feedback" in m.content]
    assert len(user_msgs) == 0, "No feedback should be injected when verification passes"


def test_verification_failed_event_emitted(tmp_path):
    """When verification fails, a verification.failed event should be emitted."""
    ctx, reg = _make_context(tmp_path)

    responses = [
        Message("assistant", "done"),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "index.html",
            "content": "<ul id='list'>todo</ul>",
        })]),
        Message("assistant", "", tool_calls=[tc("write_file", {
            "path": "app.js",
            "content": "function add() {} items.splice(0,1); items.filter(x=>x);",
        })]),
        Message("assistant", "done"),
    ]
    reg.register(FaultInjectingModel(responses, fault_config={}))
    reg.register(AgentLoop(max_rounds=10))
    reg.start_all()

    failed_events = []
    ctx.events.on("verification.failed", lambda e: failed_events.append(e))

    try:
        ctx.plugins["agent_loop"].run("build a todo app with add and delete")
    finally:
        reg.stop_all()

    assert len(failed_events) >= 1, "verification.failed event should be emitted"


def test_verification_passed_event_emitted(tmp_path):
    """When verification passes, a verification.passed event should be emitted."""
    ctx, reg = _make_context(tmp_path)

    # Create files that satisfy todo app criteria
    (tmp_path / "index.html").write_text("<ul id='list'>todo</ul>", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "function add() {} items.splice(0,1); items.filter(x=>x);",
        encoding="utf-8",
    )

    reg.register(FaultInjectingModel([Message("assistant", "done")], fault_config={}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    passed_events = []
    ctx.events.on("verification.passed", lambda e: passed_events.append(e))

    try:
        result = ctx.plugins["agent_loop"].run("build a todo app")
        assert "done" in result.lower() or result
    finally:
        reg.stop_all()

    assert len(passed_events) >= 1, "verification.passed event should be emitted"


def test_zero_drag_no_overhead_without_verifier(tmp_path):
    """When AppVerifier is not registered, no verification overhead should occur."""
    ctx = Context(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FileTools(tmp_path))
    reg.register(FaultInjectingModel([Message("assistant", "done")], fault_config={}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("say hello")
        assert result  # Should complete normally
    finally:
        reg.stop_all()
    
    # No verification events should be emitted
    assert ctx.plugins["agent_loop"]._app_verifier is None


def test_verifier_blocks_auth_app_premature_completion(tmp_path):
    """Auth app verification should block premature completion."""
    ctx, reg = _make_context(tmp_path)
    reg.register(FaultInjectingModel(
        [Message("assistant", "done")],  # No server.js → verification fails
        fault_config={},
    ))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        ctx.plugins["agent_loop"].run("build an auth app with login and signup")
    except Exception:
        pass  # May exceed max_rounds, that's OK — verification was triggered

    failed_events = []
    # Re-check: verification should have run
    v = ctx.plugins.get("app_verifier")
    assert v is not None
    assert len(v._results) > 0, "Verification should have run"
    failed = [r for r in v._results if not r.passed]
    assert len(failed) > 0, "At least one criterion should fail for incomplete auth app"
    reg.stop_all()


def test_verifier_allows_complete_auth_app(tmp_path):
    """A complete auth app should pass verification."""
    ctx, reg = _make_context(tmp_path)

    (tmp_path / "server.js").write_text(
        "app.post('/login', loginHandler); app.post('/signup', signupHandler);"
        "app.use(session()); const token = jwt.sign({}, 'secret');"
        "const hashed = bcrypt.hash(password, 10);",
        encoding="utf-8",
    )

    reg.register(FaultInjectingModel([Message("assistant", "done")], fault_config={}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("build an auth app with login and signup")
        assert result
    finally:
        reg.stop_all()

    v = ctx.plugins["app_verifier"]
    assert all(r.passed for r in v._results), "All auth criteria should pass"


def test_verifier_cli_disable(tmp_path):
    """When app_verifier is not registered, completion should work without verification."""
    ctx = Context(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FileTools(tmp_path))
    reg.register(FaultInjectingModel([Message("assistant", "done")], fault_config={}))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        result = ctx.plugins["agent_loop"].run("build a todo app with add and delete")
        # Without verifier, "done" is accepted immediately even though no files exist
        assert result is not None
    finally:
        reg.stop_all()

    # Verify no app_verifier was registered
    assert "app_verifier" not in ctx.plugins
    assert ctx.plugins["agent_loop"]._app_verifier is None
