from __future__ import annotations

import json

from pathlib import Path

from core.messages import Message
from plugins.agent.schema_router import SchemaRouter
from plugins.model import ollama as ollama_module
from plugins.model.ollama import OllamaModel
from tests.test_agent import _build_agent_with_schema, _tc_compact
from tests.test_ollama_model import TOOLS, FakeOllama


def _router() -> SchemaRouter:
    router = SchemaRouter()
    router.enabled = True
    router.compact_mode = True
    return router


def test_response_format_has_one_branch_per_logical_tool_with_required_args():
    schema = _router().get_response_format()
    branches = {b["properties"]["tool"]["const"]: b["properties"]["args"] for b in schema["anyOf"]}
    assert list(branches) == [t.name for t in SchemaRouter.LOGICAL_TOOLS]
    assert branches["write"]["required"] == ["path", "content"]
    assert branches["read"]["required"] == ["path"]
    assert branches["list"]["required"] == []
    assert branches["done"]["required"] == ["summary"]
    assert all(args["additionalProperties"] is False for args in branches.values())


def test_response_format_absent_outside_compact_mode():
    router = SchemaRouter()
    router.enabled = True
    assert router.get_response_format() is None


def test_done_summary_extraction():
    router = _router()
    assert router.done_summary([_tc_compact("done", {"summary": "wrote a.txt"})]) == "wrote a.txt"
    assert router.done_summary([_tc_compact("done", {})]) == ""
    assert router.done_summary([_tc_compact("read", {"path": "a"})]) is None


def test_options_and_format_sent_only_on_tool_turns(monkeypatch):
    fake = FakeOllama(capabilities=["completion"])
    monkeypatch.setattr(ollama_module.requests, "post", fake.post)
    fmt = _router().get_response_format()
    model = OllamaModel(model="gemma3:1b", options={"temperature": 0.0}, response_format=fmt)

    model.chat([Message(role="user", content="go")], TOOLS)
    model.chat([Message(role="user", content="summarize")], [])

    with_tools, without_tools = fake.chat_payloads()
    assert with_tools["options"] == {"temperature": 0.0}
    assert with_tools["format"] == fmt
    assert without_tools["options"] == {"temperature": 0.0}
    assert "format" not in without_tools


def test_loop_returns_done_summary_as_final_answer(tmp_path):
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "{\"tool\": \"done\"}", tool_calls=[_tc_compact("done", {"summary": "All set."})])],
    )
    try:
        assert ctx.plugins["agent_loop"].run("finish up") == "All set."
    finally:
        reg.stop_all()


def _write_existing_file_run(tmp_path, calibration):
    from tests.test_agent import build_agent, tc

    (tmp_path / "x.txt").write_text("original", encoding="utf-8")
    responses = [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "x.txt", "content": "blind"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "x.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "x.txt", "content": "informed"})]),
        Message("assistant", "done"),
    ]
    ctx, reg = build_agent(tmp_path, responses, config={"calibration": calibration} if calibration else None)
    return ctx, reg


def test_read_before_write_guard_rejects_blind_overwrite(tmp_path):
    ctx, reg = _write_existing_file_run(tmp_path, {"require_read_before_write": True})
    try:
        assert ctx.plugins["agent_loop"].run("update x.txt") == "done"
        tool_results = [m.content for m in ctx.messages if m.role == "tool"]
        assert "already exists and was not read" in tool_results[0]
        assert "original" in tool_results[0]
        assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "informed"
    finally:
        reg.stop_all()


def test_read_before_write_guard_off_by_default(tmp_path):
    (tmp_path / "x.txt").write_text("original", encoding="utf-8")
    from tests.test_agent import build_agent, tc

    ctx, reg = build_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "x.txt", "content": "blind"})]),
        Message("assistant", "done"),
    ])
    try:
        ctx.plugins["agent_loop"].run("update x.txt")
        assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "blind"
    finally:
        reg.stop_all()


def test_guard_allows_rewriting_a_file_written_this_run(tmp_path):
    from tests.test_agent import build_agent, tc

    ctx, reg = build_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "new.txt", "content": "v1"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "new.txt", "content": "v2"})]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    try:
        ctx.plugins["agent_loop"].run("make new.txt")
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "v2"
    finally:
        reg.stop_all()


class _RetryEverything:
    """Stands in for the full-profile ErrorRecoveryPlugin, which may re-execute a failed call."""

    def __init__(self):
        self.retries = 0

    def handle_failure(self, failure_type, context):
        from types import SimpleNamespace

        self.retries += 1
        return SimpleNamespace(action="retry")


def test_guard_holds_on_error_recovery_retry_path(tmp_path):
    from tests.test_agent import build_agent, tc

    (tmp_path / "x.txt").write_text("original", encoding="utf-8")
    ctx, reg = build_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "x.txt", "content": "blind"})]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    recovery = _RetryEverything()
    ctx.plugins["error_recovery"] = recovery
    try:
        ctx.plugins["agent_loop"].run("update x.txt")
        assert recovery.retries == 1
        assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "original"
    finally:
        reg.stop_all()


def test_same_write_is_allowed_after_model_saw_contents(tmp_path):
    from tests.test_agent import build_agent, tc

    (tmp_path / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    fix = tc("write_file", {"path": "add.py", "content": "def add(x, y):\n    return x + y\n"})
    ctx, reg = build_agent(tmp_path, [
        Message("assistant", "", tool_calls=[fix]),
        Message("assistant", "", tool_calls=[fix]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    try:
        ctx.plugins["agent_loop"].run("fix add.py")
        assert "x + y" in (tmp_path / "add.py").read_text(encoding="utf-8")
    finally:
        reg.stop_all()


def test_truncated_read_does_not_authorize_overwrite(tmp_path):
    from tests.test_agent import _build_agent_with_schema, _tc_compact

    big = "line\n" * 100
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")
    ctx, reg = _build_agent_with_schema(tmp_path, [
        Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "big.txt"})]),
        Message("assistant", "", tool_calls=[_tc_compact("write", {"path": "big.txt", "content": "short"})]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    try:
        ctx.plugins["agent_loop"].run("rewrite big.txt")
        assert (tmp_path / "big.txt").read_text(encoding="utf-8") == big
        tool_results = [m.content for m in ctx.messages if m.role == "tool"]
        assert "already exists and was not read" in tool_results[1]
    finally:
        reg.stop_all()


def test_compact_mode_never_rewrites_file_contents(tmp_path):
    from tests.test_agent import _build_agent_with_schema, _tc_compact

    original = '{\n  "name": "demo",\n  "content": "short",\n  "error": "line1\\nline2"\n}\n'
    (tmp_path / "data.json").write_text(original, encoding="utf-8")
    ctx, reg = _build_agent_with_schema(tmp_path, [
        Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "data.json"})]),
        Message("assistant", "done"),
    ])
    try:
        ctx.plugins["agent_loop"].run("read data.json")
        (tool_msg,) = [m.content for m in ctx.messages if m.role == "tool"]
        assert tool_msg == original
        assert "status" not in tool_msg
    finally:
        reg.stop_all()


def test_json_read_counts_as_full_when_compact_reserialization_preserves_data(tmp_path):
    from tests.test_agent import _build_agent_with_schema, _tc_compact

    (tmp_path / "app.json").write_text('{\n  "name": "demo",\n  "port": 3000\n}\n', encoding="utf-8")
    ctx, reg = _build_agent_with_schema(tmp_path, [
        Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "app.json"})]),
        Message("assistant", "", tool_calls=[_tc_compact("write", {"path": "app.json", "content": '{"name": "demo", "port": 8080}'})]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("change port")
        assert not [p for t, p in events if t == "guard.rejected"]
        assert json.loads((tmp_path / "app.json").read_text(encoding="utf-8"))["port"] == 8080
    finally:
        reg.stop_all()


def test_file_changed_after_read_requires_fresh_read(tmp_path):
    from tests.test_agent import build_agent, tc

    target = tmp_path / "x.txt"
    target.write_text("v1", encoding="utf-8")
    ctx, reg = build_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "x.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "x.txt", "content": "agent"})]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    model = ctx.plugins["ollama_model"]
    original_chat = model.chat

    def chat_with_external_edit(messages, tools):
        if model.calls == 1:
            target.write_text("changed by someone else", encoding="utf-8")
        return original_chat(messages, tools)

    model.chat = chat_with_external_edit
    try:
        ctx.plugins["agent_loop"].run("update x.txt")
        assert target.read_text(encoding="utf-8") == "changed by someone else"
    finally:
        reg.stop_all()


def test_unrelated_write_does_not_invalidate_a_read(tmp_path):
    from tests.test_agent import build_agent, tc

    (tmp_path / "config.json").write_text('{"port": 3000}', encoding="utf-8")
    ctx, reg = build_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "config.json"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "other.txt", "content": "x"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "config.json", "content": '{"port": 8080}'})]),
        Message("assistant", "done"),
    ], config={"calibration": {"require_read_before_write": True}})
    try:
        ctx.plugins["agent_loop"].run("change port")
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == '{"port": 8080}'
    finally:
        reg.stop_all()


def _repeat_agent(tmp_path, responses, calibration, with_options=True):
    from core.context import Context
    from core.registry import PluginRegistry
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools
    from tests.test_agent import FakeModel

    class RecordingModel(FakeModel):
        def __init__(self, items):
            super().__init__(items)
            self.options = {"temperature": 0.0}
            self.temperatures: list[float] = []

        def chat(self, messages, tools):
            self.temperatures.append(self.options["temperature"])
            return super().chat(messages, tools)

    ctx = Context(config={"calibration": calibration} if calibration else {})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "t.db"))
    model = RecordingModel(responses) if with_options else FakeModel(responses)
    reg.register(model)
    files = FileTools(tmp_path)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=6))
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    reg.start_all()
    return ctx, reg, model, events


REPEAT_CAL = {"repeat_retry_temperature": 0.4}


def _invocations(events, tool):
    return [p for t, p in events if t == "tool.invoked" and p.get("tool_name") == tool]


def test_repeated_failed_call_is_not_reexecuted_and_retried_at_0_4(tmp_path):
    from tests.test_agent import tc

    bad = tc("read_file", {"path": "missing.txt"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[bad]),
        Message("assistant", "", tool_calls=[bad]),
        Message("assistant", "", tool_calls=[tc("list_directory", {"path": "."})]),
        Message("assistant", "done"),
    ], REPEAT_CAL)
    try:
        assert ctx.plugins["agent_loop"].run("read missing") == "done"
        assert model.temperatures == [0.0, 0.0, 0.4, 0.0]
        assert model.options == {"temperature": 0.0}
        assert len(_invocations(events, "read_file")) == 1
        assert [t for t, _ in events].count("repeat.detected") == 1
    finally:
        reg.stop_all()


def test_repeat_after_retry_returns_typed_escalation(tmp_path):
    import pytest

    from core.outcomes import EscalationRequired
    from tests.test_agent import tc

    bad = tc("read_file", {"path": "./missing.txt"})
    same_normalized = tc("read_file", {"path": "missing.txt"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[bad]),
        Message("assistant", "", tool_calls=[same_normalized]),
        Message("assistant", "", tool_calls=[bad]),
    ], REPEAT_CAL)
    try:
        with pytest.raises(EscalationRequired) as raised:
            ctx.plugins["agent_loop"].run("read missing")
        outcome = raised.value.outcome
        assert outcome.reason == "repeated_failed_call"
        assert outcome.repeated_calls == ['read_file:{"path": "missing.txt"}@v0']
        assert outcome.retry_temperature == 0.4
        assert outcome.mutation_version == 0
        assert len(_invocations(events, "read_file")) == 1
        assert ("turn.escalated" in [t for t, _ in events]) and model.responses == []
    finally:
        reg.stop_all()


def test_same_call_after_a_mutation_is_not_a_repeat(tmp_path):
    from tests.test_agent import tc

    read = tc("read_file", {"path": "later.txt"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[read]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "later.txt", "content": "now here"})]),
        Message("assistant", "", tool_calls=[read]),
        Message("assistant", "done"),
    ], REPEAT_CAL)
    try:
        assert ctx.plugins["agent_loop"].run("wait for file") == "done"
        assert model.temperatures == [0.0, 0.0, 0.0, 0.0]
        assert len(_invocations(events, "read_file")) == 2
    finally:
        reg.stop_all()


def test_policy_rejection_is_not_a_failed_call_for_repeat_detection(tmp_path):
    from tests.test_agent import tc

    (tmp_path / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    fix = tc("write_file", {"path": "add.py", "content": "def add(a, b):\n    return a + b\n"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[fix]),
        Message("assistant", "", tool_calls=[fix]),
        Message("assistant", "done"),
    ], {**REPEAT_CAL, "require_read_before_write": True})
    try:
        assert ctx.plugins["agent_loop"].run("fix add") == "done"
        assert "a + b" in (tmp_path / "add.py").read_text(encoding="utf-8")
        assert "repeat.detected" not in [t for t, _ in events]
    finally:
        reg.stop_all()


def test_repeat_detection_off_without_calibration(tmp_path):
    from tests.test_agent import tc

    bad = tc("read_file", {"path": "missing.txt"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[bad]),
        Message("assistant", "", tool_calls=[bad]),
        Message("assistant", "done"),
    ], None)
    try:
        ctx.plugins["agent_loop"].run("read missing")
        assert model.temperatures == [0.0, 0.0, 0.0]
        assert "repeat.detected" not in [t for t, _ in events]
    finally:
        reg.stop_all()


def test_model_without_sampling_options_escalates_immediately(tmp_path):
    import pytest

    from core.outcomes import EscalationRequired
    from tests.test_agent import tc

    bad = tc("read_file", {"path": "missing.txt"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[bad]),
        Message("assistant", "", tool_calls=[bad]),
    ], REPEAT_CAL, with_options=False)
    try:
        with pytest.raises(EscalationRequired) as raised:
            ctx.plugins["agent_loop"].run("read missing")
        assert raised.value.outcome.reason == "repeat_retry_unavailable"
    finally:
        reg.stop_all()


def _truncating_agent(tmp_path, scripted):
    """scripted: list of (Message, done_reason) returned in order."""
    from core.context import Context
    from core.registry import PluginRegistry
    from core.plugin import Plugin
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools

    class ScriptedModel(Plugin):
        name = "ollama_model"

        def __init__(self):
            super().__init__()
            self.options = {"temperature": 0.0}
            self.temperatures: list[float] = []
            self.last_done_reason = None

        def chat(self, messages, tools):
            self.temperatures.append(self.options["temperature"])
            message, self.last_done_reason = scripted.pop(0)
            return message

    ctx = Context(config={"calibration": REPEAT_CAL})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "t.db"))
    model = ScriptedModel()
    reg.register(model)
    reg.register(FileTools(tmp_path))
    reg.register(AgentLoop(max_rounds=4))
    reg.start_all()
    return ctx, reg, model


def test_truncated_reply_is_retried_not_returned_as_answer(tmp_path):
    ctx, reg, model = _truncating_agent(tmp_path, [
        (Message("assistant", '{"tool": "write", "args": {"path": "docs.md", "content": "loop loop loop'), "length"),
        (Message("assistant", "done"), "stop"),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("Write the docs") == "done"
        assert model.temperatures == [0.0, 0.4]
    finally:
        reg.stop_all()


def test_truncated_twice_escalates(tmp_path):
    import pytest

    from core.outcomes import EscalationRequired

    cut = Message("assistant", '{"tool": "write", "args": {"path": "docs.md", "content": "loop')
    ctx, reg, model = _truncating_agent(tmp_path, [(cut, "length"), (cut, "length")])
    try:
        with pytest.raises(EscalationRequired) as raised:
            ctx.plugins["agent_loop"].run("Write the docs")
        assert raised.value.outcome.reason == "truncated_output"
        assert not (tmp_path / "docs.md").exists()
    finally:
        reg.stop_all()


def test_ollama_adapter_records_done_reason(monkeypatch):
    fake = FakeOllama(capabilities=["completion"])
    original_post = fake.post

    def post_with_length(url, json, timeout, stream):
        response = original_post(url, json, timeout, stream)
        if url.endswith("/api/chat") and isinstance(response._body, dict):
            response._body["done_reason"] = "length"
        return response

    monkeypatch.setattr(ollama_module.requests, "post", post_with_length)
    model = OllamaModel(model="gemma3:1b")
    model.chat([Message(role="user", content="go")], TOOLS)
    assert model.last_done_reason == "length"


def _path_guard_agent(tmp_path, responses, calibration):
    from tests.test_agent import build_agent

    ctx, reg = build_agent(tmp_path, responses, config={"calibration": calibration})
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    return ctx, reg, events


def _seed_nested_add(tmp_path):
    (tmp_path / "src" / "mathlib").mkdir(parents=True)
    (tmp_path / "src" / "mathlib" / "add.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")


def test_wrong_path_write_rejected_with_candidates_and_no_stray_file(tmp_path):
    from tests.test_agent import tc

    _seed_nested_add(tmp_path)
    ctx, reg, events = _path_guard_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "add.py", "content": "def add(a, b):\n    return a + b\n"})]),
        Message("assistant", "done"),
    ], {"require_known_paths": True})
    try:
        ctx.plugins["agent_loop"].run("Fix the bug in add.py")
        assert not (tmp_path / "add.py").exists()
        rejected = [p for t, p in events if t == "guard.rejected"]
        assert rejected == [{
            "reason": "wrong_path", "tool": "write_file", "path": "add.py", "round": 1, "mutation_version": 0,
            "conflict": "exact_basename", "candidates": ["src/mathlib/add.py"],
        }]
        tool_results = [m.content for m in ctx.messages if m.role == "tool"]
        assert "src/mathlib/add.py" in tool_results[0]
    finally:
        reg.stop_all()


def test_wrong_path_guard_then_repair_succeeds(tmp_path):
    from tests.test_agent import tc

    _seed_nested_add(tmp_path)
    ctx, reg, events = _path_guard_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "add.py"})]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "src/mathlib/add.py"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "src/mathlib/add.py", "content": "def add(a, b):\n    return a + b\n"})]),
        Message("assistant", "done"),
    ], {"require_known_paths": True, "require_read_before_write": True})
    try:
        assert ctx.plugins["agent_loop"].run("Fix the bug in add.py") == "done"
        assert "a + b" in (tmp_path / "src" / "mathlib" / "add.py").read_text(encoding="utf-8")
        assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["wrong_path"]
    finally:
        reg.stop_all()


def test_repeated_wrong_path_escalates_instead_of_looping(tmp_path):
    import pytest

    from core.outcomes import EscalationRequired
    from tests.test_agent import tc

    _seed_nested_add(tmp_path)
    wrong = tc("read_file", {"path": "add.py"})
    ctx, reg, model, events = _repeat_agent(tmp_path, [
        Message("assistant", "", tool_calls=[wrong]),
        Message("assistant", "", tool_calls=[wrong]),
        Message("assistant", "", tool_calls=[wrong]),
    ], {**REPEAT_CAL, "require_known_paths": True})
    try:
        with pytest.raises(EscalationRequired) as raised:
            ctx.plugins["agent_loop"].run("Fix the bug in add.py")
        assert raised.value.outcome.reason == "repeated_failed_call"
        assert model.temperatures == [0.0, 0.0, 0.4]
    finally:
        reg.stop_all()


def test_explicit_full_path_create_is_allowed_despite_same_name(tmp_path):
    from tests.test_agent import tc

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("docs", encoding="utf-8")
    ctx, reg, events = _path_guard_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "src/README.md", "content": "source code"})]),
        Message("assistant", "done"),
    ], {"require_known_paths": True, "require_read_before_write": True})
    try:
        ctx.plugins["agent_loop"].run("Create src/README.md with the line 'source code'.")
        assert (tmp_path / "src" / "README.md").read_text(encoding="utf-8") == "source code"
        assert not [p for t, p in events if t == "guard.rejected"]
    finally:
        reg.stop_all()


def test_path_guard_off_by_default(tmp_path):
    from tests.test_agent import tc

    _seed_nested_add(tmp_path)
    ctx, reg, events = _path_guard_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "add.py", "content": "x"})]),
        Message("assistant", "done"),
    ], {})
    try:
        ctx.plugins["agent_loop"].run("Fix the bug in add.py")
        assert (tmp_path / "add.py").exists()
        assert not [p for t, p in events if t == "guard.rejected"]
    finally:
        reg.stop_all()


def test_overwrite_guard_precedence_unchanged_for_existing_files(tmp_path):
    from tests.test_agent import tc

    _seed_nested_add(tmp_path)
    ctx, reg, events = _path_guard_agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "src/mathlib/add.py", "content": "blind"})]),
        Message("assistant", "done"),
    ], {"require_known_paths": True, "require_read_before_write": True})
    try:
        ctx.plugins["agent_loop"].run("Fix the bug in add.py")
        assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["unread_overwrite"]
        assert "a - b" in (tmp_path / "src" / "mathlib" / "add.py").read_text(encoding="utf-8")
    finally:
        reg.stop_all()


def _grounding_run(tmp_path, calibration, profile=None):
    from core.context import Context
    from core.registry import PluginRegistry
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools
    from tests.test_agent import FakeModel

    class SeeingModel(FakeModel):
        def __init__(self, items):
            super().__init__(items)
            self.seen: list[list[str]] = []

        def chat(self, messages, tools):
            self.seen.append([m.content for m in messages])
            return super().chat(messages, tools)

    _seed_nested_add(tmp_path)
    config = {"calibration": calibration, "workspace": str(tmp_path)}
    if profile:
        config.update({"profile": profile, "schema_router_enabled": True, "compact_schema": True})
    ctx = Context(config=config)
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "t.db"))
    model = SeeingModel([Message("assistant", "done")])
    reg.register(model)
    reg.register(FileTools(tmp_path))
    if profile:
        from plugins.agent.schema_router import SchemaRouter

        reg.register(SchemaRouter())
    reg.register(AgentLoop(max_rounds=2))
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    reg.start_all()
    try:
        ctx.plugins["agent_loop"].run("Fix the bug in add.py")
    finally:
        reg.stop_all()
    return model, events


def test_grounding_reaches_the_model_in_lite_envelope(tmp_path):
    model, events = _grounding_run(tmp_path, {"ground_request_paths": True}, profile="lite")
    joined = "\n".join(model.seen[0])
    assert "add.py → src/mathlib/add.py" in joined
    assert [p["lines"] for t, p in events if t == "request.grounded"] == [["add.py → src/mathlib/add.py"]]


def test_grounding_off_adds_nothing(tmp_path):
    model, events = _grounding_run(tmp_path, {}, profile="lite")
    assert "src/mathlib/add.py" not in "\n".join(model.seen[0])
    assert not [t for t, _ in events if t == "request.grounded"]


def test_wildcard_path_error_explains_how_to_recover(tmp_path):
    import pytest

    from core.errors import ToolError
    from plugins.tools.file import FileTools

    (tmp_path / "b.log").write_text("x", encoding="utf-8")
    (tmp_path / "a.log").write_text("x", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    tools = FileTools(tmp_path)
    with pytest.raises(ToolError, match=r"Wildcards are not supported\. Matching files: a\.log, b\.log\."):
        tools.delete_file("*.log")
    assert (tmp_path / "a.log").exists()
    with pytest.raises(ToolError, match="No files match"):
        tools.read_file("*.md")
    with pytest.raises(Exception) as escaped:
        tools.delete_file("../*.log")
    assert "Matching files" not in str(escaped.value)
    with pytest.raises(ToolError) as plain:
        tools.read_file("missing.txt")
    assert str(plain.value) == "File does not exist: missing.txt"


def _build(tmp_path: Path, model_name: str):
    from main import build_application

    return build_application(tmp_path / "ws", model_name, "http://127.0.0.1:9", tmp_path / "c.db", profile="lite")


def test_build_application_enables_constrained_actions_for_gemma(tmp_path):
    ctx, reg = _build(tmp_path, "gemma3:1b")
    try:
        model = ctx.plugins["ollama_model"]
        assert model.options == {"temperature": 0.0, "num_predict": 2048}
        assert model.response_format == ctx.plugins["schema_router"].get_response_format()
    finally:
        reg.stop_all()


def test_full_profile_gemma_is_constrained_with_matching_prompt(tmp_path):
    from main import build_application
    from plugins.agent.loop import LITE_COMPACT_GUIDANCE

    ctx, reg = build_application(tmp_path / "ws", "gemma3:1b", "http://127.0.0.1:9", tmp_path / "c.db", profile="full")
    try:
        assert ctx.plugins["schema_router"].compact_mode is True
        assert ctx.plugins["ollama_model"].response_format == ctx.plugins["schema_router"].get_response_format()
    finally:
        reg.stop_all()
    assert "call_tool" not in LITE_COMPACT_GUIDANCE


def test_text_tool_protocol_forces_text_actions_for_tool_capable_models(monkeypatch, tmp_path):
    fake = FakeOllama(capabilities=["completion", "tools"])
    monkeypatch.setattr(ollama_module.requests, "post", fake.post)
    model = OllamaModel(model="qwen2.5-coder:1.5b", text_tool_protocol=True)
    model.chat([Message(role="user", content="go"), Message(role="tool", content="R", tool_name="read_file")], TOOLS)
    (payload,) = fake.chat_payloads()
    assert "tools" not in payload
    assert payload["messages"][1] == {"role": "user", "content": "[tool result: read_file]\nR"}
    assert [p for p, _ in fake.calls].count("/api/show") == 0

    from main import build_application

    ctx, reg = build_application(tmp_path / "ws", "qwen2.5-coder:1.5b", "http://127.0.0.1:9", tmp_path / "c.db", profile="lite",
                                 calibration_overrides={"text_tool_protocol": True, "constrained_actions": True})
    try:
        built = ctx.plugins["ollama_model"]
        assert built.supports_native_tools() is False
        assert built.response_format == ctx.plugins["schema_router"].get_response_format()
    finally:
        reg.stop_all()


def test_build_application_leaves_qwen_unconstrained(tmp_path):
    ctx, reg = _build(tmp_path, "qwen2.5-coder:1.5b")
    try:
        model = ctx.plugins["ollama_model"]
        assert model.options is None
        assert model.response_format is None
    finally:
        reg.stop_all()
