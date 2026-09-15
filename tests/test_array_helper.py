"""Tests for the ArrayHelper plugin.

ArrayHelper is a deterministic, zero-token capability plugin that detects
array-related tasks and provides bounded guidance. It never calls the model
or executes tools directly.
"""
from __future__ import annotations

import pytest

from core.context import Context
from core.errors import ToolError
from core.messages import Message
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.agent.array_helper import ArrayHelper
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeModel(Plugin):
    name = "ollama_model"

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools):
        self.calls += 1
        return self.responses.pop(0)


def make_helper(config_overrides=None):
    config = {"profile": "lite", "workspace": "/tmp"}
    if config_overrides:
        config.update(config_overrides)
    ctx = Context(config=config)
    helper = ArrayHelper()
    helper.register(ctx)
    return helper


# ---------------------------------------------------------------------------
# Plugin structure & contract
# ---------------------------------------------------------------------------

def test_array_helper_is_plugin():
    helper = make_helper()
    assert isinstance(helper, Plugin)
    assert ArrayHelper.name == "array_helper"


def test_array_helper_has_no_dependencies():
    assert ArrayHelper.dependencies == ()


def test_array_helper_health_check():
    """Health check must verify required capability methods exist."""
    helper = make_helper()
    health = helper.health_check()
    assert health["healthy"] is True
    assert health["plugin"] == "array_helper"
    assert health["capabilities"]["analyze_task"] is True
    assert health["capabilities"]["analyze_context"] is True
    assert health["capabilities"]["review_action"] is True
    assert health["capabilities"]["build_guidance"] is True


def test_array_helper_contract_defined():
    """ArrayHelper must declare __contract__ for plugin verification."""
    contract = ArrayHelper.__contract__
    assert "provides" in contract
    assert "analyze_task" in contract["provides"]
    assert "analyze_context" in contract["provides"]
    assert "review_action" in contract["provides"]
    assert "build_guidance" in contract["provides"]
    assert contract["deterministic"] is True
    assert contract["zero_token"] is True


def test_array_helper_resets_run_state():
    """Per-run state must reset between runs (Invariant A)."""
    helper = make_helper()
    helper._array_facts = {"old": "data"}
    helper._facts_digest = "abc123"
    helper.reset_run_state()
    assert helper._array_facts == {}
    assert helper._facts_digest is None


# ---------------------------------------------------------------------------
# Relevance detection (deterministic, zero-token)
# ---------------------------------------------------------------------------

def test_analyze_task_relevant_filter():
    """Filter tasks with array keywords should be detected as relevant."""
    helper = make_helper()
    result = helper.analyze_task("filter the list of products to only show active items")
    assert result["relevant"] is True
    assert result["confidence"] in ("medium", "high")
    assert result["operation"] == "filter"


def test_analyze_task_relevant_sort():
    helper = make_helper()
    result = helper.analyze_task("sort the array of tasks by priority")
    assert result["relevant"] is True
    assert result["operation"] == "sort"


def test_analyze_task_not_relevant_simple_chat():
    """Non-array tasks should not be flagged as relevant."""
    helper = make_helper()
    result = helper.analyze_task("say hello")
    assert result["relevant"] is False


def test_analyze_task_not_relevant_general():
    helper = make_helper()
    result = helper.analyze_task("write a file with hello content")
    assert result["relevant"] is False


def test_analyze_task_detects_risk_delete():
    """Tasks that may delete data should flag risks."""
    helper = make_helper()
    result = helper.analyze_task("delete all invalid entries from the list")
    assert result["relevant"] is True
    assert "may_delete_data" in result["risks"]


def test_analyze_task_detects_risk_sort():
    helper = make_helper()
    result = helper.analyze_task("sort the records alphabetically")
    assert "index_reordering" in result["risks"]


def test_analyze_task_confidence_high():
    """Multiple keywords + operation should be high confidence."""
    helper = make_helper()
    result = helper.analyze_task("filter the items in the list and sort by index")
    assert result["confidence"] == "high"


def test_analyze_task_confidence_low():
    """Single keyword, no operation should be low confidence."""
    helper = make_helper()
    result = helper.analyze_task("list")
    assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# Context analysis (deterministic, after file read)
# ---------------------------------------------------------------------------

def test_analyze_context_json_list_flat():
    """JSON flat list should be detected."""
    helper = make_helper()
    result = helper.analyze_context('["a", "b", "c"]')
    assert result["shape"] == "flat"
    assert result["element_type"] == "strings"


def test_analyze_context_json_list_of_objects():
    """JSON list of objects should be detected as list_of_objects."""
    helper = make_helper()
    result = helper.analyze_context('[{"name": "a", "id": 1}, {"name": "b", "id": 2}]')
    assert result["shape"] == "list_of_objects"
    assert "name" in result["fields"]
    assert "id" in result["fields"]


def test_analyze_context_unknown_format():
    """Non-array content should return unknown/low confidence."""
    helper = make_helper()
    result = helper.analyze_context("Hello world, this is a string.")
    assert result["confidence"] == "low"


def test_analyze_context_capped_excerpt():
    """Long excerpts should be capped to prevent token bloat."""
    helper = make_helper()
    long_excerpt = "x" * 10000
    result = helper.analyze_context(long_excerpt)
    # Should not crash and should return low confidence for non-array data
    assert result["confidence"] == "low"


def test_analyze_context_matrix_detected():
    helper = make_helper()
    result = helper.analyze_context("[[1, 2], [3, 4]]")
    assert result["shape"] == "nested"


# ---------------------------------------------------------------------------
# Action review (deterministic)
# ---------------------------------------------------------------------------

def test_review_action_write_passes_for_safe():
    """Writing filter operations should pass."""
    helper = make_helper()
    array_facts = {"shape": "flat", "operation": "filter"}
    arguments = {"path": "app.js", "content": "const visible = items.filter(x => x.active);"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "pass"


def test_review_action_write_warns_for_sort_mutation():
    """Using .sort() should warn about mutation risk."""
    helper = make_helper()
    array_facts = {"shape": "flat"}
    arguments = {"path": "app.js", "content": "items.sort((a, b) => a - b);"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "warn"
    assert "sort" in result["reason"].lower()


def test_review_action_write_warns_for_reverse_mutation():
    helper = make_helper()
    array_facts = {"shape": "flat"}
    arguments = {"path": "app.js", "content": "items.reverse();"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "warn"
    assert "reverse" in result["reason"].lower()


def test_review_action_warns_for_unsafe_index_access():
    """Index access without empty check should warn."""
    helper = make_helper()
    array_facts = {"shape": "flat"}
    arguments = {"path": "app.js", "content": "const first = items[0];"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "warn"


def test_review_action_non_write_tool_passes():
    """Non-write tools should default to pass."""
    helper = make_helper()
    result = helper.review_action("read_file", {"path": "data.txt"}, {"shape": "flat"})
    assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# Bounded guidance builder
# ---------------------------------------------------------------------------

def test_build_guidance_is_bounded():
    """Guidance must be compact (under 150 words)."""
    helper = make_helper()
    array_facts = {
        "representation": "javascript_array",
        "shape": "list_of_objects",
        "operation": "filter",
        "mutation_risk": "low",
    }
    guidance = helper.build_guidance(array_facts)
    word_count = len(guidance.split())
    assert word_count <= 150


def test_build_guidance_includes_operation_advice():
    helper = make_helper()
    array_facts = {"operation": "filter"}
    guidance = helper.build_guidance(array_facts)
    assert "filter" in guidance.lower()


def test_build_guidance_includes_empty_handling():
    """Guidance should always mention empty list handling."""
    helper = make_helper()
    guidance = helper.build_guidance({})
    assert "empty" in guidance.lower()


def test_build_guidance_empty_facts_minimal():
    helper = make_helper()
    guidance = helper.build_guidance({})
    assert isinstance(guidance, str)
    assert len(guidance) < 200


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def test_get_facts_returns_copy():
    """get_facts must return a copy, not the internal dict."""
    helper = make_helper()
    helper.update_facts({"shape": "flat"})
    retrieved = helper.get_facts()
    retrieved["modified"] = True
    assert "modified" not in helper.get_facts()


def test_update_facts_detects_changes():
    helper = make_helper()
    changed1 = helper.update_facts({"shape": "flat", "operation": "filter"})
    changed2 = helper.update_facts({"shape": "list_of_objects", "operation": "filter"})
    assert changed1 is True
    assert changed2 is True


def test_update_facts_no_change_on_same():
    helper = make_helper()
    helper.update_facts({"shape": "flat"})
    changed = helper.update_facts({"shape": "flat"})
    assert changed is False


def test_clear_facts_removes_all():
    helper = make_helper()
    helper.update_facts({"shape": "flat"})
    helper.clear_facts()
    assert helper.get_facts() == {}


# ---------------------------------------------------------------------------
# Zero-drag invariant tests
# ---------------------------------------------------------------------------

def test_zero_drag_helper_never_calls_model():
    """ArrayHelper must never call the model — all methods are deterministic."""
    helper = make_helper()
    # These methods should not require any model plugin
    helper.analyze_task("test")
    helper.analyze_context("[]")
    helper.review_action("write_file", {"content": "x"}, {"shape": "flat"})
    helper.build_guidance({"operation": "filter"})
    # If this doesn't crash, the helper is truly zero-token


# ---------------------------------------------------------------------------
# Integration with AgentLoop (zero-drag + relevant activation)
# ---------------------------------------------------------------------------

def test_zero_drag_no_activation_on_non_array_task(tmp_path):
    """When ArrayHelper is registered but task is non-array, no array events
    should be emitted and no guidance should be injected."""
    from core.messages import Message as Msg
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools

    ctx = Ctx(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel([Msg("assistant", "done")]))
    reg.register(FileTools(tmp_path))
    reg.register(ArrayHelper())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        array_events = []
        ctx.events.on("array.analysis.completed", lambda e: array_events.append(e))
        ctx.plugins["agent_loop"].run("say hello")

        assert len(array_events) == 0, "ArrayHelper activated on non-array task"
        # No prompt injections should have been added by array helper
        assert ctx.prompt_injections == [], "ArrayHelper injected context for non-array task"
    finally:
        reg.stop_all()


@pytest.mark.parametrize("array_guidance, expect_hint", [(True, True), (False, False)])
def test_array_guidance_calibration_controls_hint_injection(tmp_path, array_guidance, expect_hint):
    from core.messages import Message as Msg
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools

    class SeeingModel(FakeModel):
        def __init__(self, responses):
            super().__init__(responses)
            self.seen = []

        def chat(self, messages, tools):
            self.seen.extend(m.content for m in messages)
            return super().chat(messages, tools)

    ctx = Ctx(config={"workspace": str(tmp_path), "calibration": {"array_guidance": array_guidance}})
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    list_call = {"function": {"name": "list_directory", "arguments": {"path": "."}}}
    model = SeeingModel([Msg("assistant", "", tool_calls=[list_call]), Msg("assistant", "done")])
    reg.register(model)
    reg.register(FileTools(tmp_path))
    reg.register(ArrayHelper())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()
    try:
        ctx.plugins["agent_loop"].run("Filter the items array to remove duplicates by id")
        assert any("[array context]" in text for text in model.seen) is expect_hint
    finally:
        reg.stop_all()


def test_array_helper_activates_on_array_task(tmp_path):
    """When an array task is detected, array events should be emitted."""
    from core.messages import Message as Msg
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools

    ctx = Ctx(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel([Msg("assistant", "done")]))
    reg.register(FileTools(tmp_path))
    reg.register(ArrayHelper())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        array_events = []
        ctx.events.on("array.analysis.completed", lambda e: array_events.append(e))
        ctx.plugins["agent_loop"].run("filter the list of products by status")

        assert len(array_events) >= 1, "ArrayHelper should activate on array task"
        event_types = [e.type for e in array_events]
        assert "array.analysis.completed" in event_types
    finally:
        reg.stop_all()


def test_array_helper_resets_per_run(tmp_path):
    """ArrayHelper must reset transient state between runs."""
    from core.messages import Message as Msg
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools

    ctx = Ctx(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel([Msg("assistant", "done"), Msg("assistant", "done")]))
    reg.register(FileTools(tmp_path))
    reg.register(ArrayHelper())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        helper = ctx.plugins["array_helper"]
        helper.update_facts({"shape": "flat"})
        assert helper._facts_digest is not None

        # Run 1 — should reset state
        ctx.plugins["agent_loop"].run("say hello")
        assert helper._facts_digest is None or helper._array_facts == {}

        # Run 2 — should also reset
        ctx.plugins["agent_loop"].run("say hello again")
        assert helper._facts_digest is None or helper._array_facts == {}
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Enhancement 1: ArrayHelper registered in lite/full profiles
# ---------------------------------------------------------------------------

def test_array_helper_enabled_in_lite_profile():
    """ArrayHelper must be registered in the lite profile."""
    import tempfile
    import shutil
    from pathlib import Path
    from main import build_application

    tmp = tempfile.mkdtemp(prefix="ah_lite_")
    tmp_path = Path(tmp)
    try:
        ws = tmp_path / "workspace"
        ws.mkdir()
        db = tmp_path / "test.db"
        ctx, reg = build_application(ws, "qwen2.5-coder:1.5b", "http://127.0.0.1:11434", db, profile="lite")
        try:
            assert "array_helper" in ctx.plugins, "ArrayHelper not registered in lite profile"
            assert ctx.plugins["array_helper"].name == "array_helper"
            assert ctx.plugins["array_helper"].health_check()["healthy"] is True
            assert "app_verifier" in ctx.plugins, "AppVerifier should be registered in lite profile"
        finally:
            reg.stop_all()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_array_helper_enabled_in_full_profile():
    """ArrayHelper must be registered in the full profile."""
    import tempfile
    import shutil
    from pathlib import Path
    from main import build_application

    tmp = tempfile.mkdtemp(prefix="ah_full_")
    tmp_path = Path(tmp)
    try:
        ws = tmp_path / "workspace"
        ws.mkdir()
        db = tmp_path / "test.db"
        ctx, reg = build_application(ws, "qwen2.5-coder:1.5b", "http://127.0.0.1:11434", db, profile="full")
        try:
            assert "array_helper" in ctx.plugins, "ArrayHelper not registered in full profile"
            assert ctx.plugins["array_helper"].name == "array_helper"
            assert "app_verifier" in ctx.plugins, "AppVerifier should be registered in full profile"
        finally:
            reg.stop_all()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_array_helper_zero_drag_after_enable(tmp_path):
    """After enabling ArrayHelper in profiles, non-array tasks must have zero drag."""
    from core.messages import Message as Msg
    from core.context import Context as Ctx
    from core.registry import PluginRegistry as Reg
    from plugins.core.event_logger import EventLogger

    ctx = Ctx(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = Reg(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel([Msg("assistant", "done")]))
    reg.register(FileTools(tmp_path))
    reg.register(ArrayHelper())
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    try:
        system_msgs_before = len([m for m in ctx.messages if m.role == "system"])
        ctx.plugins["agent_loop"].run("create a.txt with hello")
        system_msgs_after = len([m for m in ctx.messages if m.role == "system"])
        
        # Only the expected tool guidance system message, no array guidance
        assert system_msgs_after == system_msgs_before + 1
        assert ctx.prompt_injections == [], "ArrayHelper injected context for non-array task"
    finally:
        reg.stop_all()


# ---------------------------------------------------------------------------
# Enhancement 3: Numerical arrays support
# ---------------------------------------------------------------------------

def test_analyze_context_numerical_flat_list():
    """Numerical flat list should be detected with element_type 'numbers'."""
    helper = make_helper()
    result = helper.analyze_context("[1, 2, 3, 4, 5]")
    assert result["representation"] == "json_or_js_array"
    assert result["shape"] == "flat"
    assert result["element_type"] == "numbers"
    assert result["confidence"] == "high"


def test_analyze_context_numerical_list_of_objects():
    """Numerical fields in objects should be detected as element_type 'numbers_or_mixed'."""
    helper = make_helper()
    result = helper.analyze_context('[{"score": 10, "name": "a"}, {"score": 20, "name": "b"}]')
    assert result["shape"] == "list_of_objects"
    assert result["element_type"] == "numbers_or_mixed"
    assert "score" in result["fields"]
    assert "name" in result["fields"]


def test_analyze_context_floats_detected():
    """Floating point arrays should be detected as numbers."""
    helper = make_helper()
    result = helper.analyze_context("[1.5, 2.7, 3.14, 0.001]")
    assert result["element_type"] == "numbers"
    assert result["confidence"] == "high"


def test_analyze_context_empty_list_is_low_confidence():
    """Empty list should return low confidence."""
    helper = make_helper()
    result = helper.analyze_context("[]")
    assert result["confidence"] == "low"


def test_analyze_task_numerical_aggregate():
    """Statistical aggregate tasks should be detected."""
    helper = make_helper()
    result = helper.analyze_task("calculate the average and sum of the numbers in the array")
    assert result["relevant"] is True
    assert result["confidence"] in ("medium", "high")


def test_review_action_numerical_safe_filter():
    """Safe numerical filter should pass."""
    helper = make_helper()
    array_facts = {"shape": "flat", "element_type": "numbers", "operation": "filter"}
    arguments = {"path": "calc.js", "content": "const evens = nums.filter(n => n % 2 === 0);"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "pass"


def test_review_action_warns_on_integer_division():
    """Integer division in numerical operations should warn."""
    helper = make_helper()
    array_facts = {"shape": "flat", "element_type": "numbers"}
    arguments = {"path": "calc.js", "content": "const avg = sum / count; // integer division risk"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "warn"


def test_review_action_warns_on_modulo_zero():
    """Modulo or division by zero risk should warn."""
    helper = make_helper()
    array_facts = {"shape": "flat", "element_type": "numbers"}
    arguments = {"path": "calc.js", "content": "const result = nums[0] / nums[1];"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "warn"


def test_review_action_numerical_reduce_passes():
    """Safe reduce/sum pattern should pass."""
    helper = make_helper()
    array_facts = {"shape": "flat", "element_type": "numbers", "operation": "aggregate"}
    arguments = {"path": "calc.js", "content": "const total = nums.reduce((sum, n) => sum + n, 0);"}
    result = helper.review_action("write_file", arguments, array_facts)
    assert result["status"] == "pass"


def test_build_guidance_numerical_advice():
    """Numerical arrays should include precision and empty handling advice."""
    helper = make_helper()
    array_facts = {"element_type": "numbers", "operation": "aggregate", "shape": "flat"}
    guidance = helper.build_guidance(array_facts)
    assert "empty" in guidance.lower()
    assert "number" in guidance.lower()


def test_build_guidance_float_precision_warning():
    """Floating point operations should mention precision concerns."""
    helper = make_helper()
    array_facts = {"element_type": "numbers", "operation": "aggregate"}
    guidance = helper.build_guidance(array_facts)
    # Should mention floating point considerations
    assert "float" in guidance.lower() or "precision" in guidance.lower() or "number" in guidance.lower()
