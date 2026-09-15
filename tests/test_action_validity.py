from __future__ import annotations

from benchmark.action_validity import action_violation
from plugins.agent.schema_router import SchemaRouter


def _schema():
    router = SchemaRouter()
    router.enabled = True
    router.compact_mode = True
    return router.get_response_format()


def test_executable_actions_are_valid():
    schema = _schema()
    assert action_violation('{"tool": "write", "args": {"path": "a.txt", "content": "hi"}}', schema) is None
    assert action_violation('{"tool": "list", "args": {}}', schema) is None
    assert action_violation('{"tool": "done", "args": {"summary": "ok"}}', schema) is None


def test_violations_are_named():
    schema = _schema()
    assert action_violation("Sure, I will read it.", schema) == "not_json"
    assert action_violation('{"tool": "write", "args": {"path": "a.txt"}}', schema) == "missing:content"
    assert action_violation('{"tool": "read", "args": {"path": "a", "mode": "r"}}', schema) == "extra:mode"
    assert action_violation('{"tool": "format_disk", "args": {}}', schema) == "unknown_tool:format_disk"
    assert action_violation('{"tool_calls": []}', schema) == "wrong_shape"
    assert action_violation('{"tool": "done", "args": {}}', schema) == "missing:summary"
