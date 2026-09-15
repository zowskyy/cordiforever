import json
from pathlib import Path

import pytest

from core.context import Context
from core.errors import ToolError
from core.messages import Message
from core.plugin import Plugin
from core.reality import RealityProjector
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop, TOKEN_BUDGET
from plugins.agent.schema_router import SchemaRouter
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools


class FakeModel(Plugin):
    name = "ollama_model"

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        return self.responses.pop(0)


def build_agent(tmp_path, responses, config=None):
    from core.messages import Message

    ctx = Context(config=config or {})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel(responses))
    reg.register(FileTools(tmp_path))
    reg.register(AgentLoop())
    reg.start_all()
    return ctx, reg


def tc(name, args):
    return {"function": {"name": name, "arguments": args}}


def test_agent_single_tool_call_roundtrip(tmp_path):
    from core.messages import Message

    tool_call = tc("write_file", {"path": "a.txt", "content": "hello"})
    ctx, reg = build_agent(tmp_path, [Message("assistant", "", tool_calls=[tool_call]), Message("assistant", "done")])
    assert ctx.plugins["agent_loop"].run("create a file") == "done"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
    assert ctx.messages[2].tool_calls == [tool_call]
    assert ctx.messages[3].role == "tool"
    reg.stop_all()


def test_agent_multiple_tool_calls(tmp_path):
    from core.messages import Message

    calls = [tc("write_file", {"path": "a.txt", "content": "a"}), tc("write_file", {"path": "b.txt", "content": "b"})]
    ctx, reg = build_agent(tmp_path, [Message("assistant", "", tool_calls=calls), Message("assistant", "both done")])
    result = ctx.plugins["agent_loop"].run("make two files")
    # 3x: loop now continues until model emits done (not auto-done), so result is model-provided "both done"
    assert "done" in result.lower()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "b"
    reg.stop_all()


def test_agent_handles_tool_error(tmp_path):
    from core.messages import Message

    bad_call = tc("read_file", {"path": "../secret.txt"})
    ctx, reg = build_agent(tmp_path, [Message("assistant", "", tool_calls=[bad_call]), Message("assistant", "I recovered")])
    assert ctx.plugins["agent_loop"].run("read secret") == "I recovered"
    tool_msgs = [m for m in ctx.messages if m.role == "tool"]
    payload = json.loads(tool_msgs[0].content)
    assert "error" in payload
    reg.stop_all()


def test_agent_maintains_history_across_rounds(tmp_path):
    from core.messages import Message

    ctx, reg = build_agent(tmp_path, [Message("assistant", "first")])
    assert ctx.plugins["agent_loop"].run("hello") == "first"
    assert [m.role for m in ctx.messages] == ["user", "system", "assistant"]
    reg.stop_all()


def test_agent_emits_events(tmp_path):
    from core.messages import Message

    tool_call = tc("write_file", {"path": "a.txt", "content": "hello"})
    ctx, reg = build_agent(tmp_path, [Message("assistant", "", tool_calls=[tool_call]), Message("assistant", "done")])
    ctx.plugins["agent_loop"].run("create a file")
    el = ctx.plugins["event_logger"]
    types = [e.type for e in el.event_log.get_session_events(el.continuity.session_id)]
    assert {"session.start", "user.message", "tool.result"}.issubset(types)
    reg.stop_all()


class CapturingModel(Plugin):
    name = "ollama_model"
    dependencies = ()

    def __init__(self):
        super().__init__()
        self.seen: list = []

    def chat(self, messages, tools):
        self.seen.append(list(messages))
        return Message("assistant", "done")


def test_agent_lite_uses_envelope(tmp_path):
    ctx = Context(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    model = CapturingModel()
    reg.register(model)
    reg.register(FileTools(tmp_path))
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()
    try:
        result = ctx.plugins["agent_loop"].run("hello")
        assert result == "done"
        loop = ctx.plugins["agent_loop"]
        fed = model.seen[-1]
        # Invariant 1: lite feeds the compiled envelope, never the mutable cache.
        assert fed is not ctx.messages
        assert [m.role for m in fed] == ["system", "user"]
        assert fed[0].role == "system"
        assert fed[0].content == loop._system_prompt
        assert fed[1].role == "user"
        assert "hello" in fed[1].content
        # Invariant 3: compilation is deterministic over (log, manifest, assets).
        event_log = ctx.plugins["event_logger"].event_log
        sid = loop._get_session_id()
        a = RealityProjector(event_log).compile_request(sid, loop._manifest, loop._system_prompt, loop._tool_schemas, TOKEN_BUDGET)
        b = RealityProjector(event_log).compile_request(sid, loop._manifest, loop._system_prompt, loop._tool_schemas, TOKEN_BUDGET)
        assert a.full_request_hash == b.full_request_hash
        assert a.request_prefix_hash == b.request_prefix_hash
    finally:
        reg.stop_all()


def test_tool_result_truncated_to_calibrated_limit(tmp_path):
    """33k window protection: a single tool result must never exceed its
    calibrated byte cap (1.5b preset: 8192 bytes) — one result cannot swallow
    the window regardless of file size on disk. Truncation is marked so the
    model knows the file continues."""
    from core.context import MODEL_PRESETS, DEFAULT_PRESET_KEY

    ctx, reg = build_agent(tmp_path, [Message("assistant", "done")])
    try:
        limit = MODEL_PRESETS[DEFAULT_PRESET_KEY]["max_tool_result_bytes"]
        loop = ctx.plugins["agent_loop"]
        loop._record_tool_result("read_file", {"path": "big.txt"}, "x" * (limit + 5000), True)
        content = ctx.messages[-1].content
        assert len(content.encode("utf-8")) <= limit + 100  # + marker overhead
        assert content[:limit] == "x" * limit
        assert "truncated" in content
    finally:
        reg.stop_all()


def test_tool_result_limit_follows_calibration_override(tmp_path):
    """Calibration separation: the tool-result cap comes from
    Context.config["calibration"] (merged over the preset), not a loop literal."""
    ctx, reg = build_agent(
        tmp_path, [Message("assistant", "done")],
        config={"calibration": {"max_tool_result_bytes": 100}},
    )
    try:
        loop = ctx.plugins["agent_loop"]
        assert loop._max_result_bytes == 100
        loop._record_tool_result("read_file", {"path": "b.txt"}, "y" * 500, True)
        content = ctx.messages[-1].content
        assert len(content.encode("utf-8")) <= 100 + 100
        assert "truncated" in content
    finally:
        reg.stop_all()


def test_multi_domain_llm_fallback_gated_by_profile_and_flag():
    """P0 zero-token guarantee: the multi-domain LLM fallback for unresolved
    fragments must run ONLY in the full profile AND with --enable-semantic-router.
    Otherwise the multi-domain path is abandoned (query falls through to the
    deterministic routers + agent loop) and _call_llm_directly is never called."""
    from plugins.agent.multi_domain_router import DomainResult, MultiDomainResult
    from plugins.agent.query_splitter import Fragment

    class _StubMultiDomain:
        def route_multi(self, text, ctx):
            return MultiDomainResult(
                results=[
                    DomainResult(fragment=Fragment(text="derivative", domain="math"), domain="math", response="2*x"),
                    DomainResult(fragment=Fragment(text="pizza", domain="general"), domain="general", response=None),
                ],
                has_unresolved=True,
            )

    def make_loop(config):
        loop = AgentLoop()
        loop.register(Context(config=config))
        loop._multi_domain_router = _StubMultiDomain()
        loop._aggregator = object()
        routed = []
        loop._call_llm_directly = lambda text: (routed.append(text) or "llm-answer")
        return loop, routed

    query = "What is the derivative of x squared? And how is pizza made?"

    # lite (default profile): no routing LLM, multi-domain abandoned
    loop, routed = make_loop({"profile": "lite"})
    loop._try_multi_domain(query)
    assert routed == []
    assert loop._multi_domain_results == []

    # full without flag: still no routing LLM
    loop, routed = make_loop({"profile": "full"})
    loop._try_multi_domain(query)
    assert routed == []
    assert loop._multi_domain_results == []

    # full + explicit flag: fallback allowed
    loop, routed = make_loop({"profile": "full", "semantic_router_enabled": True})
    loop._try_multi_domain(query)
    assert routed == ["pizza"]
    assert len(loop._multi_domain_results) == 2


def test_lite_profile_excludes_semantic_router_and_embedding(tmp_path):
    """Profile isolation: lite profile must not register semantic_router or
    embedding_model at runtime, and AgentLoop must see _semantic_router=None."""
    ctx = Context(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel([Message("assistant", "done")]))
    reg.register(FileTools(tmp_path))
    reg.register(AgentLoop())
    reg.start_all()
    try:
        assert "semantic_router" not in ctx.plugins
        assert "embedding_model" not in ctx.plugins
        loop = ctx.plugins["agent_loop"]
        assert loop._semantic_router is None
    finally:
        reg.stop_all()

def test_injected_content_is_user_role_and_prefixed(tmp_path):
    """Injection hardening: prompt injections must be inserted as user messages
    with the exact '[injected context]' prefix, never as system."""
    ctx, reg = build_agent(tmp_path, [Message("assistant", "done")])
    try:
        ctx.prompt_injections.append(Message("injection", "secret context"))
        ctx.plugins["agent_loop"].run("hello")
        injected = [m for m in ctx.messages if "injected context" in (m.content or "")]
        assert len(injected) == 1
        assert injected[0].role == "user"
        assert injected[0].content.startswith("[injected context]")
    finally:
        reg.stop_all()


def test_prompt_injections_cleared_after_processing(tmp_path):
    """Injection hardening: prompt_injections list must be cleared after use."""
    ctx, reg = build_agent(tmp_path, [Message("assistant", "done")])
    try:
        ctx.prompt_injections.append(Message("injection", "once"))
        ctx.prompt_injections.append(Message("injection", "twice"))
        ctx.plugins["agent_loop"].run("hello")
        assert ctx.prompt_injections == []
    finally:
        reg.stop_all()


def test_agent_emits_exactly_one_turn_start_and_one_turn_end(tmp_path):
    """Event hygiene: one turn.start and one turn.end per agent run."""
    ctx, reg = build_agent(tmp_path, [Message("assistant", "done")])
    try:
        ctx.plugins["agent_loop"].run("hello")
        sid = ctx.plugins["event_logger"].continuity.session_id
        events = ctx.plugins["event_logger"].event_log.get_session_events(sid)
        types = [e.type for e in events]
        assert types.count("turn.start") == 1
        assert types.count("turn.end") == 1
    finally:
        reg.stop_all()


def test_agent_emits_turn_round_once_per_iteration(tmp_path):
    """Event hygiene: turn.round emitted once per loop iteration, not duplicated."""
    ctx, reg = build_agent(tmp_path, [Message("assistant", "done")])
    try:
        seen: list[str] = []
        ctx.events.on("turn.round", lambda e: seen.append(e.type))
        ctx.plugins["agent_loop"].run("hello")
        assert seen.count("turn.round") == 1
    finally:
        reg.stop_all()


def test_duplicate_successful_tool_calls_are_filtered(tmp_path):
    """P0 loop fix: when the model repeats a previously successful tool call,
    the agent must filter it out before execution and guide the model to reply
    with text instead, preventing max_rounds_exceeded loops."""
    from core.messages import Message

    tool_call = tc("write_file", {"path": "a.txt", "content": "hi"})
    # First response: valid tool call. Second response: duplicate tool call.
    # Third response: text reply after guidance.
    ctx, reg = build_agent(
        tmp_path,
        [
            Message("assistant", "", tool_calls=[tool_call]),
            Message("assistant", "", tool_calls=[tool_call]),
            Message("assistant", "already done"),
        ],
    )
    try:
        result = ctx.plugins["agent_loop"].run("hi")
        assert result == "already done"
        # Verify the file was written exactly once
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
        # Verify we did not hit max_rounds_exceeded
        tool_msgs = [m for m in ctx.messages if m.role == "tool"]
        duplicate_errors = [m for m in tool_msgs if '"duplicate": true' in (m.content or "")]
        assert duplicate_errors == []
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# SchemaRouter integration tests
# ---------------------------------------------------------------------------

def _tc_compact(logical_name: str, args: dict):
    """Build a compact-schema tool_call as the model would emit it."""
    return {
        "id": f"call_{logical_name}",
        "type": "function",
        "function": {
            "name": "call_tool",
            "arguments": {"tool": logical_name, "args": args},
        },
    }


def _build_agent_with_schema(tmp_path, responses, profile="lite", compact_schema=True, config=None):
    """Build an agent with SchemaRouter registered and configured."""
    _config = {"profile": profile, "workspace": str(tmp_path), "schema_router_enabled": True, "compact_schema": compact_schema}
    if config:
        _config.update(config)
    ctx = Context(config=_config)
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel(responses))
    reg.register(FileTools(tmp_path))
    reg.register(SchemaRouter())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()
    return ctx, reg


def test_compact_schema_active_in_lite_loop(tmp_path):
    """When compact_schema is enabled, AgentLoop should use compact schemas for the model."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=True,
    )
    try:
        loop = ctx.plugins["agent_loop"]
        router = ctx.plugins["schema_router"]
        assert router.enabled is True
        assert router.compact_mode is True

        active = loop._get_active_tool_schemas()
        # Should be the single compact schema, not the verbose per-tool schemas
        assert len(active) == 1
        assert active[0]["function"]["name"] == "call_tool"
    finally:
        reg.stop_all()


def test_compact_schema_not_active_when_disabled(tmp_path):
    """When compact_schema is False, AgentLoop should use verbose schemas."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=False,
    )
    try:
        loop = ctx.plugins["agent_loop"]
        active = loop._get_active_tool_schemas()
        # Should fall back to verbose per-tool schemas
        names = [s["function"]["name"] for s in active]
        assert "read_file" in names
        assert "write_file" in names
        assert "call_tool" not in names
    finally:
        reg.stop_all()


def test_agent_loop_expands_compact_write_call(tmp_path):
    """The model calls call_tool(write, {path, content}); the loop should
    expand it to write_file and execute, creating the file."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [
            Message("assistant", "", tool_calls=[_tc_compact("write", {"path": "a.txt", "content": "hi"})]),
            Message("assistant", "done"),
        ],
        profile="lite",
        compact_schema=True,
    )
    try:
        result = ctx.plugins["agent_loop"].run("write hi to a.txt")
        assert result == "done"
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    finally:
        reg.stop_all()


def test_agent_loop_expands_compact_read_call(tmp_path):
    """The model calls call_tool(read, {path}); the loop should expand it
    to read_file and execute, returning the file content."""
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [
            Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "b.txt"})]),
            Message("assistant", "world"),
        ],
        profile="lite",
        compact_schema=True,
    )
    try:
        result = ctx.plugins["agent_loop"].run("read b.txt")
        assert result == "world"
    finally:
        reg.stop_all()


def test_agent_loop_done_logical_ends_turn(tmp_path):
    """When the model calls call_tool(done, {}), no real tool is executed
    and the loop returns the model's text content."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "", tool_calls=[_tc_compact("done", {})])],
        profile="lite",
        compact_schema=True,
    )
    try:
        # After expansion, 'done' produces no real tool calls.
        # The loop sees empty tool_calls and returns the model's content.
        result = ctx.plugins["agent_loop"].run("done with task")
        # No tool message should have been appended
        tool_msgs = [m for m in ctx.messages if m.role == "tool"]
        assert len(tool_msgs) == 0
    finally:
        reg.stop_all()


def test_agent_loop_compact_result_compression(tmp_path):
    """When compact mode is on, tool results from read_file should be compressed
    (truncated) before being added to context."""
    large_content = "A" * 500
    (tmp_path / "big.txt").write_text(large_content, encoding="utf-8")

    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [
            Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "big.txt"})]),
            Message("assistant", "done"),
        ],
        profile="lite",
        compact_schema=True,
    )
    try:
        ctx.plugins["agent_loop"].run("read big.txt")
        tool_msgs = [m for m in ctx.messages if m.role == "tool"]
        assert len(tool_msgs) > 0
        # The result should be truncated (not the full 500 chars)
        content = tool_msgs[0].content
        # read_file returns raw string content; compression truncates to ~200 chars + "..."
        assert len(content) <= 203  # 200 chars + "..."
        assert content.endswith("...")
    finally:
        reg.stop_all()


def test_compact_schema_zero_token_for_pattern_tasks(tmp_path):
    """Zero-thought router patterns still work with compact_schema enabled.
    File operations matching patterns should still be 0-token (zero round)."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [],  # No model responses needed — zero-thought router handles it
        profile="lite",
        compact_schema=True,
    )
    try:
        # This should be handled by zero-thought router, not the model
        result = ctx.plugins["agent_loop"].run("write hello to a.txt")
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
        # Verify no model calls were made
        model = ctx.plugins["ollama_model"]
        assert model.calls == 0
    finally:
        reg.stop_all()


def test_compact_schema_lite_still_zero_token_for_read(tmp_path):
    """Reading a file via zero-thought router should be 0-token in lite."""
    (tmp_path / "test.txt").write_text("content", encoding="utf-8")
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [],  # No model responses needed — zero-thought router handles it
        profile="lite",
        compact_schema=True,
    )
    try:
        result = ctx.plugins["agent_loop"].run("read test.txt")
        assert "content" in result
        model = ctx.plugins["ollama_model"]
        assert model.calls == 0
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Zero-thought router pattern tests (simple_chat, delete_file)
# ---------------------------------------------------------------------------

def test_zero_thought_greeting_is_zero_token(tmp_path):
    """'say hello' should be handled by the zero-thought router (0 model calls)."""
    from plugins.agent.specialized_routers import SpecializedRouters

    tool_handlers = {}
    record_calls: list = []

    def fake_record(tool_name, arguments, result, success):
        record_calls.append((tool_name, result, success))

    router = SpecializedRouters(
        tool_handlers=tool_handlers,
        context=Context(config={"profile": "lite"}),
        record_tool_result=fake_record,
        resolve_path=lambda p: None,
    )
    result = router.try_zero_thought("say hello")
    assert result is not None
    assert "hello" in result.lower()
    # Zero-thought: no tool calls should have been recorded
    assert len(record_calls) == 0


def test_zero_thought_hello_is_zero_token(tmp_path):
    """'say hello' should be handled by the zero-thought router."""
    from plugins.agent.specialized_routers import SpecializedRouters

    router = SpecializedRouters(
        tool_handlers={},
        context=Context(config={"profile": "lite"}),
        record_tool_result=lambda *a: None,
        resolve_path=lambda p: None,
    )
    result = router.try_zero_thought("say hello")
    assert result is not None
    assert len(result) > 0


def test_zero_thought_delete_nonexistent_file(tmp_path):
    """'delete b.txt' where b.txt doesn't exist should report the error, 0-token."""
    from plugins.agent.specialized_routers import SpecializedRouters

    record_calls: list = []

    def fake_record(tool_name, arguments, result, success):
        record_calls.append((tool_name, result, success))

    # Create a mock resolve_path that returns None (file doesn't exist)
    router = SpecializedRouters(
        tool_handlers={"read_file": lambda name, args: "exists"},
        context=Context(config={}),
        record_tool_result=fake_record,
        resolve_path=lambda p: None,
    )
    result = router.try_zero_thought("delete b.txt")
    assert result is not None
    assert "does not exist" in result.lower() or "not found" in result.lower()


def test_zero_thought_delete_existing_file(tmp_path):
    """'delete a.txt' where a.txt exists should delete it, 0-token."""
    from plugins.agent.specialized_routers import SpecializedRouters

    # Set up a real FileTools instance
    files = FileTools(tmp_path)
    files.start()
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    record_calls: list = []

    def fake_record(tool_name, arguments, result, success):
        record_calls.append((tool_name, result, success))

    router = SpecializedRouters(
        tool_handlers={"delete_file": files.execute},
        context=Context(config={}),
        record_tool_result=fake_record,
        resolve_path=files._resolve,
    )
    result = router.try_zero_thought("delete a.txt")
    assert result is not None
    # File should be deleted
    assert not (tmp_path / "a.txt").exists()
    # Result should indicate success
    assert "deleted" in result.lower() or "success" in result.lower() or "ok" in result.lower()


# ---------------------------------------------------------------------------
# End-to-end zero-token tests with measurement harness
# ---------------------------------------------------------------------------

def test_simple_chat_zero_token_in_lite(tmp_path):
    """End-to-end: 'say hello' should be 0-token (zero-thought router)."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [],  # No model responses needed
        profile="lite",
        compact_schema=True,
    )
    try:
        result = ctx.plugins["agent_loop"].run("say hello")
        model = ctx.plugins["ollama_model"]
        assert model.calls == 0
        assert len(result) > 0
    finally:
        reg.stop_all()


def test_delete_file_zero_token_for_nonexistent(tmp_path):
    """End-to-end: 'delete b.txt' (nonexistent) should be 0-token."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [],  # No model responses needed
        profile="lite",
        compact_schema=True,
    )
    try:
        result = ctx.plugins["agent_loop"].run("delete b.txt")
        model = ctx.plugins["ollama_model"]
        assert model.calls == 0
        assert "does not exist" in result.lower() or "not found" in result.lower()
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Continuity Kernel invariants
# ---------------------------------------------------------------------------

def test_state_reconstruction_from_events(tmp_path):
    """Invariant: task state can be reconstructed from canonical event history.

    After a run that writes a file, the essential task state (goal, tools used,
    files touched) must be reconstructable from events alone — without retaining
    any in-memory task_state.
    """
    tool_call = tc("write_file", {"path": "reconstruct.txt", "content": "data"})
    ctx, reg = build_agent(
        tmp_path,
        [Message("assistant", "", tool_calls=[tool_call]), Message("assistant", "done")],
    )
    try:
        result = ctx.plugins["agent_loop"].run("write data to reconstruct.txt")

        # Capture session info before closing
        el = ctx.plugins["event_logger"]
        session_id = el.continuity.session_id
        db_path = el.event_log._db_path
    finally:
        reg.stop_all()

    # Reconstruct state from a fresh EventLog pointing at the same DB
    from core.event_log import EventLog

    with EventLog(db_path) as new_log:
        events = new_log.get_session_events(session_id)

        # Goal is reconstructable from user.message event
        user_events = [e for e in events if e.type == "user.message"]
        assert len(user_events) >= 1
        reconstructed_goal = user_events[0].payload.get("content", "")
        assert "reconstruct.txt" in reconstructed_goal

        # Tools used are reconstructable from tool.invoked events
        invoked_events = [e for e in events if e.type == "tool.invoked"]
        tools_used = [e.payload.get("tool_name") for e in invoked_events]
        assert "write_file" in tools_used

        # Files touched are reconstructable from tool.invoked arguments
        files_touched = []
        for e in invoked_events:
            args = e.payload.get("arguments", {})
            if isinstance(args, dict) and "path" in args:
                files_touched.append(args["path"])
        assert "reconstruct.txt" in files_touched


def test_calibration_immutable_after_run(tmp_path):
    """Invariant: token budgets and calibration values cannot change mid-run."""
    from core.calibration import resolve_calibration

    cal = resolve_calibration("qwen2.5-coder:1.5b")
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=True,
        config={"calibration": cal},
    )
    try:
        # Snapshot calibration before run
        cal_before = dict(ctx.config["calibration"])
        loop = ctx.plugins["agent_loop"]
        budget_before = loop._token_budget
        max_result_before = loop._max_result_bytes

        ctx.plugins["agent_loop"].run("hello")

        # Verify calibration hasn't changed
        cal_after = dict(ctx.config["calibration"])
        assert cal_after == cal_before, "Calibration dict was mutated during run"
        assert loop._token_budget == budget_before, "Token budget changed during run"
        assert loop._max_result_bytes == max_result_before, "Max result bytes changed during run"
    finally:
        reg.stop_all()


def test_no_hidden_context_in_prompt(tmp_path):
    """Invariant: all model-visible context is traceable through events or prompts.

    After a run, every injected context must come from:
    1. context.prompt_injections (cleared after use), or
    2. the canonical event history
    """
    ctx, reg = build_agent(
        tmp_path,
        [Message("assistant", "done")],
        config={"profile": "lite"},
    )
    try:
        ctx.prompt_injections.append(Message("user", "[injected context] test"))
        ctx.plugins["agent_loop"].run("hello")

        # prompt_injections must be cleared after use
        assert ctx.prompt_injections == [], "Prompt injections not cleared after run"
    finally:
        reg.stop_all()


def test_plugin_health_check_schema_router(tmp_path):
    """Plugin health verification: SchemaRouter must expose required capabilities."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=True,
    )
    try:
        router = ctx.plugins["schema_router"]
        health = router.health_check()
        assert health["enabled"] is True
        assert health["compact_mode"] is True
        assert health["has_get_model_tools"] is True
        assert health["has_expand_call"] is True
        assert health["has_compress_result"] is True
    finally:
        reg.stop_all()


def test_plugin_health_check_file_tools(tmp_path):
    """Plugin health verification: FileTools must expose protected-file enforcement."""
    ctx, reg = build_agent(
        tmp_path,
        [Message("assistant", "done")],
    )
    try:
        files = ctx.plugins["file_tools"]
        health = files.health_check()
        assert health["healthy"] is True
        assert health["protected_files_enforced"] is True
        assert health["protected_count"] >= 1  # AGENTS.md at minimum
    finally:
        reg.stop_all()


def test_turn_round_logged_to_event_store(tmp_path):
    """Event taxonomy: turn.round must be logged to the durable event store."""
    tool_call = tc("write_file", {"path": "log_test.txt", "content": "data"})
    ctx, reg = build_agent(
        tmp_path,
        [Message("assistant", "", tool_calls=[tool_call]), Message("assistant", "done")],
    )
    try:
        ctx.plugins["agent_loop"].run("create log_test.txt")
        el = ctx.plugins["event_logger"]
        sid = el.continuity.session_id
        events = el.event_log.get_session_events(sid)
        types = [e.type for e in events]
        # turn.round must appear in the durable event store
        assert "turn.round" in types, "turn.round not logged to event store"
        round_count = types.count("turn.round")
        assert round_count >= 1, f"Expected at least 1 turn.round, got {round_count}"
    finally:
        reg.stop_all()


def test_protected_file_violation_event_logged(tmp_path):
    """Event taxonomy: protected_file.violation must be emitted and logged."""
    ctx, reg = build_agent(
        tmp_path,
        [Message("assistant", "done")],
    )
    try:
        # Create AGENTS.md in workspace
        (tmp_path / "AGENTS.md").write_text("# instructions", encoding="utf-8")

        violations: list = []
        ctx.events.on("protected_file.violation", lambda e: violations.append(e))

        files = ctx.plugins["file_tools"]
        with pytest.raises(ToolError, match="(?i)protected"):
            files.write_file("AGENTS.md", "# modified")

        assert len(violations) == 1
        assert violations[0].payload["file"] == "AGENTS.md"
        assert violations[0].payload["operation"] == "access"

        # Verify it was logged to the event store
        el = ctx.plugins["event_logger"]
        sid = el.continuity.session_id
        stored_events = el.event_log.get_session_events(sid)
        violation_events = [e for e in stored_events if e.type == "protected_file.violation"]
        assert len(violation_events) == 1
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Phase 7: Duplicate-call prevention hardening
# ---------------------------------------------------------------------------

def test_duplicate_call_signature_normalizes_formatting(tmp_path):
    """Canonical signature: calls with different JSON formatting but
    semantically identical arguments must produce the same signature."""
    from core.messages import Message

    loop = AgentLoop()
    # Same args, different key order and spacing
    call_a = tc("write_file", {"path": "a.txt", "content": "hi"})
    call_b = tc("write_file", {"content": "hi", "path": "a.txt"})
    sig_a = loop._sig(call_a)
    sig_b = loop._sig(call_b)
    assert sig_a == sig_b, "Signatures differ for semantically identical calls"


def test_duplicate_call_signature_different_args_differ(tmp_path):
    """Canonical signature: calls with different argument values must differ."""
    loop = AgentLoop()
    call_a = tc("write_file", {"path": "a.txt", "content": "hi"})
    call_b = tc("write_file", {"path": "a.txt", "content": "bye"})
    assert loop._sig(call_a) != loop._sig(call_b)


def test_repeated_failed_calls_blocked_after_threshold(tmp_path):
    """After 2 failures for the same signature, subsequent calls are blocked."""
    from core.messages import Message

    # Model calls write_file with an absolute path (always fails: WorkspaceError)
    bad_call = tc("write_file", {"path": "/etc/evil.txt", "content": "hi"})
    ctx, reg = build_agent(
        tmp_path,
        [
            Message("assistant", "", tool_calls=[bad_call]),
            Message("assistant", "", tool_calls=[bad_call]),
            Message("assistant", "", tool_calls=[bad_call]),
            Message("assistant", "gave up"),
        ],
    )
    try:
        result = ctx.plugins["agent_loop"].run("try to write")
        # After 2 failures, the 3rd call is blocked
        loop = ctx.plugins["agent_loop"]
        sig = loop._sig(bad_call)
        assert loop._blocked(sig), "Call should be blocked after 2 failures"
        # Model eventually gives up
        assert "gave" in result.lower()
    finally:
        reg.stop_all()


def test_all_duplicates_falls_back_to_text(tmp_path):
    """When all candidate calls are duplicates of successful ones,
    the model is guided toward a text response."""
    from core.messages import Message

    tool_call = tc("write_file", {"path": "dupe.txt", "content": "data"})
    ctx, reg = build_agent(
        tmp_path,
        [
            Message("assistant", "", tool_calls=[tool_call]),
            Message("assistant", "", tool_calls=[tool_call]),
            Message("assistant", "", tool_calls=[tool_call]),
            Message("assistant", "all done via text"),
        ],
    )
    try:
        result = ctx.plugins["agent_loop"].run("create dupe.txt")
        # File written once
        assert (tmp_path / "dupe.txt").read_text(encoding="utf-8") == "data"
        # Final result is the text response, not a tool call
        assert "done" in result.lower()
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Phase 8: Zero-drag invariant tests
# ---------------------------------------------------------------------------

def test_zero_drag_irrelevant_capability_no_extra_messages(tmp_path):
    """When SchemaRouter is registered but compact_schema=False (verbose mode),
    no extra system messages should be added to context."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=False,
    )
    try:
        system_msgs_before = len([m for m in ctx.messages if m.role == "system"])
        ctx.plugins["agent_loop"].run("hello")
        system_msgs_after = len([m for m in ctx.messages if m.role == "system"])
        # Only the expected tool_guidance system message should be added
        # No extra compact-schema system messages
        assert system_msgs_after == system_msgs_before + 1
    finally:
        reg.stop_all()


def test_zero_drag_irrelevant_capability_no_extra_tool_schemas(tmp_path):
    """When compact_schema=False, the model must see verbose schemas, not compact."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=False,
    )
    try:
        loop = ctx.plugins["agent_loop"]
        schemas = loop._get_active_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        # Verbose schemas — no call_tool
        assert "call_tool" not in names
        assert "write_file" in names
    finally:
        reg.stop_all()


def test_zero_drag_compact_mode_uses_single_schema(tmp_path):
    """When compact_schema=True, the model should see exactly one call_tool schema."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=True,
    )
    try:
        loop = ctx.plugins["agent_loop"]
        schemas = loop._get_active_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "call_tool"
    finally:
        reg.stop_all()


def test_zero_drag_budget_unchanged_with_schema_router(tmp_path):
    """SchemaRouter must not increase the token budget — it reduces visible tokens."""
    from core.calibration import resolve_calibration

    cal = resolve_calibration("qwen2.5-coder:1.5b")
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=True,
        config={"calibration": cal},
    )
    try:
        loop = ctx.plugins["agent_loop"]
        assert loop._token_budget == cal["pruner_budget"]
        assert loop._max_result_bytes == cal["max_tool_result_bytes"]
    finally:
        reg.stop_all()


def test_zero_drag_compact_schema_smaller_than_verbose(tmp_path):
    """The compact schema must be smaller than verbose per-tool schemas."""
    from plugins.agent.schema_router import SchemaRouter

    router = SchemaRouter()
    router.register(Context(config={"schema_router_enabled": True, "compact_schema": True, "profile": "lite"}))

    verbose = ctx_plugins_schemas(tmp_path)
    compact = router.get_model_tools()

    verbose_text = json.dumps(verbose, ensure_ascii=False, separators=(",", ":"))
    compact_text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    assert len(compact_text) < len(verbose_text) * 0.5, (
        f"Compact schema ({len(compact_text)} chars) should be <50% of verbose ({len(verbose_text)} chars)"
    )


def test_zero_drag_verbose_mode_uses_full_schemas(tmp_path):
    """When compact_schema=False, the model must see verbose schemas in run."""
    ctx, reg = _build_agent_with_schema(
        tmp_path,
        [Message("assistant", "done")],
        profile="lite",
        compact_schema=False,
    )
    try:
        loop = ctx.plugins["agent_loop"]
        schemas = loop._get_active_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        # Verbose mode — should show real tool names, not call_tool
        assert "call_tool" not in names
        assert "write_file" in names
        assert "read_file" in names
        assert "list_directory" in names
        # And the schema should be larger than compact
        router = ctx.plugins.get("schema_router")
        if router is not None and getattr(router, "enabled", False):
            verbose_json = json.dumps(schemas, ensure_ascii=False, separators=(",", ":"))
            compact = router.get_model_tools()
            compact_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            assert len(compact_json) < len(verbose_json)
    finally:
        reg.stop_all()


def ctx_plugins_schemas(tmp_path):
    """Helper: get verbose tool schemas from a fresh FileTools."""
    files = FileTools(tmp_path)
    return files.schemas()
