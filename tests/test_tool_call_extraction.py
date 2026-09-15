from __future__ import annotations

from core.tool_call_extraction import extract_tool_calls_from_text
from plugins.agent.schema_router import SchemaRouter


def _compact_tools():
    router = SchemaRouter()
    router.enabled = True
    router.compact_mode = True
    return router, router.get_model_tools()


VERBOSE_TOOLS = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]


def _expanded(text):
    router, tools = _compact_tools()
    calls = extract_tool_calls_from_text(text, tools)
    assert calls, f"no call extracted from {text!r}"
    return router.expand_call(calls[0])["function"]


def test_canonical_compact_call_still_parses():
    fn = _expanded('{"tool_calls":[{"function":{"name":"call_tool","arguments":{"tool":"read","args":{"path":"a.txt"}}}}]}')
    assert fn == {"name": "read_file", "arguments": {"path": "a.txt"}}


def test_bare_tool_args_object_is_wrapped():
    fn = _expanded('```json\n{"tool": "write", "args": {"path": "h.py", "content": "print(1)"}}\n```')
    assert fn == {"name": "write_file", "arguments": {"path": "h.py", "content": "print(1)"}}


def test_name_arguments_with_logical_name_is_wrapped():
    fn = _expanded('Sure: {"name": "read", "arguments": {"path": "config.json"}}')
    assert fn == {"name": "read_file", "arguments": {"path": "config.json"}}


def test_logical_name_inside_tool_calls_list_is_wrapped():
    fn = _expanded('{"tool_calls":[{"function":{"name":"list","arguments":{"path":"tests"}}}]}')
    assert fn == {"name": "list_directory", "arguments": {"path": "tests"}}


def test_unknown_logical_name_is_not_wrapped():
    _, tools = _compact_tools()
    assert extract_tool_calls_from_text('{"tool": "format_disk", "args": {}}', tools) == []


def test_verbose_schemas_do_not_accept_bare_tool_objects():
    assert extract_tool_calls_from_text('{"tool": "read", "args": {"path": "a"}}', VERBOSE_TOOLS) == []
    calls = extract_tool_calls_from_text('{"name": "read_file", "arguments": {"path": "a"}}', VERBOSE_TOOLS)
    assert calls[0]["function"] == {"name": "read_file", "arguments": {"path": "a"}}
