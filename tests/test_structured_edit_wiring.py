from __future__ import annotations

import json

import pytest

from core.errors import ToolError
from core.messages import Message
from plugins.tools.file import FileTools
from tests.test_agent import _build_agent_with_schema, _tc_compact

STRUCTURED = {"calibration": {"structured_edits": True, "require_known_paths": True, "require_read_before_write": True}}
CONFIG = '{\n  "name": "demo",\n  "port": 3000,\n  "hosts": ["a", "b"]\n}\n'
BUGGY = "def add(a, b):\n    return a - b\n"


def _seed(tmp_path):
    (tmp_path / "src" / "mathlib").mkdir(parents=True)
    (tmp_path / "src" / "mathlib" / "add.py").write_text(BUGGY, encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.json").write_text(CONFIG, encoding="utf-8")


def _read(path):
    return _tc_compact("read", {"path": path})


def _run(tmp_path, calls, config=STRUCTURED):
    _seed(tmp_path)
    responses = [Message("assistant", "", tool_calls=[c]) for c in calls] + [Message("assistant", "done")]
    ctx, reg = _build_agent_with_schema(tmp_path, responses, profile="lite", compact_schema=True, config=config)
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("do the edit")
    finally:
        reg.stop_all()
    tool_results = [m.content for m in ctx.messages if m.role == "tool"]
    rejections = [p["reason"] for t, p in events if t == "guard.rejected"]
    return ctx, rejections, tool_results


def _add_text(tmp_path):
    return (tmp_path / "src" / "mathlib" / "add.py").read_text(encoding="utf-8")


def _config_text(tmp_path):
    return (tmp_path / "config" / "app.json").read_text(encoding="utf-8")


def test_replace_after_read_fixes_expression(tmp_path):
    _, rejections, results = _run(tmp_path, [_read("src/mathlib/add.py"), _tc_compact("replace", {"path": "src/mathlib/add.py", "old": "return a - b", "new": "return a + b"})])
    assert _add_text(tmp_path) == "def add(a, b):\n    return a + b\n"
    assert rejections == []
    assert "Replaced 1 occurrence in src/mathlib/add.py at line 2" in results[1]


def test_unread_keyword_replace_is_refused_and_shows_contents(tmp_path):
    # Observed: gemma replaced "add" with "subtract" without reading the file.
    _, rejections, results = _run(tmp_path, [_tc_compact("replace", {"path": "src/mathlib/add.py", "old": "add", "new": "subtract"})])
    assert _add_text(tmp_path) == BUGGY
    assert rejections == ["unread_edit"]
    assert "not read before editing" in results[0] and "return a - b" in results[0]


def test_prose_contaminated_replace_is_rejected_and_file_unchanged(tmp_path):
    _, _, results = _run(tmp_path, [_read("src/mathlib/add.py"), _tc_compact("replace", {"path": "src/mathlib/add.py", "old": "return a - b", "new": "return a + b\n\nAdd the two numbers together."})])
    assert _add_text(tmp_path) == BUGGY
    assert "no longer be valid Python" in results[1]


def test_patch_json_changes_port_and_preserves_all_other_fields_and_format(tmp_path):
    _, rejections, results = _run(tmp_path, [_read("config/app.json"), _tc_compact("patch_json", {"path": "config/app.json", "set": {"/port": 8080}})])
    text = _config_text(tmp_path)
    assert json.loads(text) == {"name": "demo", "port": 8080, "hosts": ["a", "b"]}
    assert text.startswith('{\n  "name": "demo",') and text.endswith("\n")
    assert results[1] == "Patched config/app.json: /port: 3000 -> 8080"
    assert rejections == []


def test_text_replace_on_json_is_refused_even_after_read(tmp_path):
    # Observed: gemma replaced "port" with "8080" in config.json, renaming the key while keeping valid JSON.
    _, rejections, results = _run(tmp_path, [_read("config/app.json"), _tc_compact("replace", {"path": "config/app.json", "old": "port", "new": "8080"})])
    assert _config_text(tmp_path) == CONFIG
    assert rejections == ["json_requires_patch"]
    assert "patch_json" in results[1]


def test_overwrite_of_existing_structured_file_is_refused(tmp_path):
    _, rejections, results = _run(tmp_path, [_read("config/app.json"), _tc_compact("write", {"path": "config/app.json", "content": "Port: 8080"})])
    assert _config_text(tmp_path) == CONFIG
    assert rejections == ["overwrite_existing_file"]
    assert "cannot be overwritten" in results[1] and "patch_json" in results[1]


def test_root_replacement_patch_is_impossible(tmp_path):
    _, _, results = _run(tmp_path, [_read("config/app.json"), _tc_compact("patch_json", {"path": "config/app.json", "set": {"": {"port": 8080}}})])
    assert _config_text(tmp_path) == CONFIG
    assert "whole document" in results[1]


def test_type_changing_patch_is_refused(tmp_path):
    _, _, results = _run(tmp_path, [_read("config/app.json"), _tc_compact("patch_json", {"path": "config/app.json", "set": {"/port": "8080"}})])
    assert _config_text(tmp_path) == CONFIG
    assert "refusing to replace it with a string" in results[1]


def test_write_still_creates_new_files(tmp_path):
    _, rejections, _ = _run(tmp_path, [_tc_compact("write", {"path": "count.txt", "content": "3"})])
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "3"
    assert rejections == []


def test_replace_on_wrong_path_is_refused_with_candidates(tmp_path):
    ctx, rejections, results = _run(tmp_path, [_tc_compact("replace", {"path": "add.py", "old": "return a - b", "new": "return a + b"})])
    assert rejections == ["wrong_path"]
    assert "src/mathlib/add.py" in results[0]


def test_structured_tools_absent_without_calibration(tmp_path):
    ctx, _, _ = _run(tmp_path, [_tc_compact("replace", {"path": "src/mathlib/add.py", "old": "return a - b", "new": "return a + b"})], config=None)
    assert _add_text(tmp_path) == BUGGY
    enum = ctx.plugins["schema_router"].get_model_tools()[0]["function"]["parameters"]["properties"]["tool"]["enum"]
    assert "replace" not in enum and "patch_json" not in enum
    assert not {"replace_text", "patch_json"} & {s["function"]["name"] for s in ctx.plugins["file_tools"].schemas()}


def test_structured_router_schema_branches(tmp_path):
    ctx, _, _ = _run(tmp_path, [], config=STRUCTURED)
    router = ctx.plugins["schema_router"]
    branches = {b["properties"]["tool"]["const"]: b["properties"]["args"] for b in router.get_response_format()["anyOf"]}
    assert list(branches) == ["read", "write", "list", "delete", "replace", "patch_json", "done"]
    assert branches["patch_json"]["required"] == ["path", "set"]
    assert branches["patch_json"]["properties"]["remove"] == {"type": "array", "items": {"type": "string"}}


def test_file_tool_execute_refuses_structured_tools_when_disabled(tmp_path):
    _seed(tmp_path)
    tools = FileTools(tmp_path)
    with pytest.raises(ToolError, match="Unknown file tool"):
        tools.execute("replace_text", {"path": "src/mathlib/add.py", "old": "a - b", "new": "a + b"})


def test_mutation_version_advances_on_structured_edit(tmp_path):
    ctx, _, _ = _run(tmp_path, [_read("config/app.json"), _tc_compact("patch_json", {"path": "config/app.json", "set": {"/port": 8080}})])
    assert ctx.plugins["agent_loop"]._mutation_version == 1
