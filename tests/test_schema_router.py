"""Tests for the SchemaRouter compact-schema plugin.

TDD Red phase: these tests verify the compact-schema behavior before
the plugin is implemented.
"""
import json

import pytest

from core.context import Context
from core.errors import ToolError
from core.messages import Message
from core.plugin import Plugin
from plugins.agent.schema_router import SchemaRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_router(config_overrides: dict | None = None):
    config = {"profile": "lite", "workspace": "/tmp", "model": "qwen2.5-coder:1.5b"}
    if config_overrides:
        config.update(config_overrides)
    ctx = Context(config=config)
    router = SchemaRouter()
    router.register(ctx)
    return router


# ---------------------------------------------------------------------------
# Plugin structure
# ---------------------------------------------------------------------------

def test_schema_router_is_plugin():
    router = make_router()
    assert isinstance(router, Plugin)
    assert SchemaRouter.name == "schema_router"


def test_schema_router_disabled_by_default():
    router = make_router()
    assert router.enabled is False


def test_schema_router_enabled_via_config():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    assert router.enabled is True
    assert router.compact_mode is True


# ---------------------------------------------------------------------------
# Compact schema generation
# ---------------------------------------------------------------------------

def test_compact_schema_returns_single_call_tool_when_enabled():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    tools = router.get_model_tools()
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "call_tool"


def test_compact_schema_lists_logical_tools():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    tools = router.get_model_tools()
    fn = tools[0]["function"]
    enum_values = fn["parameters"]["properties"]["tool"]["enum"]
    for logical in ("read", "write", "list", "done"):
        assert logical in enum_values


def test_verbose_schema_returns_empty_when_disabled():
    router = make_router({"schema_router_enabled": False, "compact_schema": True})
    tools = router.get_model_tools()
    assert tools == []


def test_compact_schema_is_smaller_than_verbose():
    """The compact schema must be significantly smaller than verbose per-tool schemas."""
    from plugins.tools.file import FileTools
    import tempfile

    tmp = tempfile.mkdtemp()
    files = FileTools(tmp)
    verbose_schemas = files.schemas()
    verbose_text = json.dumps(verbose_schemas, ensure_ascii=False, separators=(",", ":"))

    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    compact_schemas = router.get_model_tools()
    compact_text = json.dumps(compact_schemas, ensure_ascii=False, separators=(",", ":"))

    # Compact should be substantially smaller (target: at least 50% reduction)
    assert len(compact_text) < len(verbose_text) * 0.5


# ---------------------------------------------------------------------------
# Expansion — accepts full model-format call dict
# ---------------------------------------------------------------------------

def _compact_call(logical_name: str, args: dict):
    """Build a compact-schema tool call as the model would emit it."""
    return {
        "id": f"call_{logical_name}",
        "type": "function",
        "function": {
            "name": "call_tool",
            "arguments": {"tool": logical_name, "args": args},
        },
    }


def test_expand_read():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    expanded = router.expand_call(_compact_call("read", {"path": "a.txt"}))
    assert expanded == {"id": "call_read", "type": "function", "function": {"name": "read_file", "arguments": {"path": "a.txt"}}}


def test_expand_write():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    expanded = router.expand_call(_compact_call("write", {"path": "a.txt", "content": "hello"}))
    assert expanded == {"id": "call_write", "type": "function", "function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}


def test_expand_list_with_path():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    expanded = router.expand_call(_compact_call("list", {"path": "src"}))
    assert expanded == {"id": "call_list", "type": "function", "function": {"name": "list_directory", "arguments": {"path": "src"}}}


def test_expand_list_default_path():
    """When path is omitted, default to '.'"""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    expanded = router.expand_call(_compact_call("list", {}))
    assert expanded == {"id": "call_list", "type": "function", "function": {"name": "list_directory", "arguments": {"path": "."}}}


def test_expand_done_returns_none():
    """'done' is a sentinel — no real tool to call."""
    router = make_router()
    expanded = router.expand_call(_compact_call("done", {}))
    assert expanded is None


def test_expand_unknown_tool_returns_none():
    router = make_router()
    expanded = router.expand_call(_compact_call("nonexistent", {"x": 1}))
    assert expanded is None


def test_expand_disabled_router_returns_none():
    """When router is disabled, expand should return None for everything."""
    router = make_router()  # enabled=False by default
    assert router.expand_call(_compact_call("read", {"path": "a.txt"})) is None


def test_expand_all_logical_tools():
    """Every logical tool in the compact schema should have an expansion rule."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    tools = router.get_model_tools()
    enum_values = tools[0]["function"]["parameters"]["properties"]["tool"]["enum"]
    for logical in enum_values:
        if logical == "done":
            assert router.expand_call(_compact_call(logical, {})) is None
        else:
            # Must expand to a real tool
            expanded = router.expand_call(_compact_call(logical, {"path": "test"}))
            assert expanded is not None
            assert expanded["function"]["name"] != "call_tool"


def test_expand_call_accepts_string_arguments():
    """Model may emit arguments as a JSON string, not a dict.

    The expand_call method must parse both dict and JSON-string arguments
    to handle the real model-format compact call.
    """
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    call = {
        "id": "call_read",
        "type": "function",
        "function": {
            "name": "call_tool",
            "arguments": '{"tool": "read", "args": {"path": "a.txt"}}',
        },
    }
    expanded = router.expand_call(call)
    assert expanded is not None
    assert expanded["function"]["name"] == "read_file"
    assert expanded["function"]["arguments"] == {"path": "a.txt"}


def test_expand_call_preserves_id():
    """The expanded call should preserve the original call id."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    call = _compact_call("write", {"path": "a.txt", "content": "hi"})
    call["id"] = "custom_call_id_123"
    expanded = router.expand_call(call)
    assert expanded["id"] == "custom_call_id_123"


def test_expand_call_passthrough_non_compact():
    """Non-call_tool calls should pass through unchanged."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    passthrough = {
        "id": "call_real",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": {"path": "a.txt"},
        },
    }
    result = router.expand_call(passthrough)
    assert result == passthrough


# ---------------------------------------------------------------------------
# Result compression
# ---------------------------------------------------------------------------

def test_compress_result_large_content():
    """Large file content should be truncated to a preview."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    result = {"content": "x" * 500, "status": "ok"}
    compressed = router.compress_result(result)
    assert "content_preview" in compressed
    assert len(compressed["content_preview"]) <= 203  # 200 + "..."
    assert compressed["content_preview"].endswith("...")


def test_compress_result_small_content():
    """Small content should be kept as-is."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    result = {"content": "hello", "status": "ok"}
    compressed = router.compress_result(result)
    assert compressed["content"] == "hello"


def test_compress_result_preserves_path_and_status():
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    result = {"path": "a.txt", "content": "x" * 500, "status": "ok"}
    compressed = router.compress_result(result)
    assert compressed["path"] == "a.txt"
    assert compressed["status"] == "ok"


def test_compress_result_error_truncated():
    """Error messages should be truncated to first line."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    result = {"error": "Error: something broke\nat line 1\nat line 2", "status": "error"}
    compressed = router.compress_result(result)
    assert "\n" not in compressed["error"]


def test_compress_result_disabled_returns_original():
    """When compact_mode is off, compress_result returns the input unchanged."""
    router = make_router({"schema_router_enabled": True, "compact_schema": False})
    result = {"content": "x" * 500}
    assert router.compress_result(result) is result


def test_compress_non_json_result():
    """Non-JSON result strings should be wrapped in a minimal dict."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    result = "Wrote 42 bytes to a.txt"
    compressed = router.compress_result(result)
    # Should produce a JSON-serializable dict, not crash
    json.dumps(compressed)  # must not raise


# ---------------------------------------------------------------------------
# Integration: SchemaRouter registered in a Context
# ---------------------------------------------------------------------------

def test_schema_router_available_via_context_plugins():
    """AgentLoop lookups use context.plugins.get('schema_router')."""
    ctx = Context(config={"profile": "lite", "schema_router_enabled": True, "compact_schema": True})
    router = SchemaRouter()
    router.register(ctx)
    ctx.plugins["schema_router"] = router
    assert ctx.plugins["schema_router"].enabled is True


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def test_schema_router_health_check_enabled():
    """Health check must verify required capability methods exist."""
    router = make_router({"schema_router_enabled": True, "compact_schema": True})
    health = router.health_check()
    assert health["healthy"] is True
    assert health["enabled"] is True
    assert health["compact_mode"] is True
    assert health["has_get_model_tools"] is True
    assert health["has_expand_call"] is True
    assert health["has_compress_result"] is True


def test_schema_router_health_check_disabled():
    """Disabled router health check should report healthy=False."""
    router = make_router()  # enabled=False
    health = router.health_check()
    assert health["healthy"] is False
    assert health["enabled"] is False


def test_schema_router_contract_defined():
    """SchemaRouter must declare its contract for plugin verification."""
    contract = getattr(SchemaRouter, "__contract__", {})
    assert "requires" in contract
    assert "provides" in contract
    assert "schema_router_enabled" in contract["requires"]
    assert "compact_schema" in contract["provides"]
