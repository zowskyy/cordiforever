from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.errors import ToolError
from core.messages import Message
from plugins.agent.loop import REPO_TOOLS_GUIDANCE
from plugins.tools.file import FileTools
from tests.test_agent import _build_agent_with_schema, _tc_compact

MATHLIB = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "mathlib"
REPO_ON = {"calibration": {"repo_tools": True}}


def _run(tmp_path, calls, config=REPO_ON):
    workspace = tmp_path / "ws"
    shutil.copytree(MATHLIB, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    responses = [Message("assistant", "", tool_calls=[c]) for c in calls] + [Message("assistant", "done")]

    seen: list[str] = []
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config=config)
    model = ctx.plugins["ollama_model"]
    original = model.chat

    def recording(messages, tools):
        seen.extend(m.content for m in messages)
        return original(messages, tools)

    model.chat = recording
    try:
        ctx.plugins["agent_loop"].run("locate subtract")
    finally:
        reg.stop_all()
    tool_results = [m.content for m in ctx.messages if m.role == "tool"]
    return ctx, tool_results, seen


def test_repo_tools_execute_through_the_loop_without_compact_truncation(tmp_path):
    _, results, seen = _run(tmp_path, [
        _tc_compact("repo_outline", {}),
        _tc_compact("find_symbol", {"name": "subtract"}),
    ])
    from core.repo_index import RepositoryIndex

    assert results[0] == RepositoryIndex(tmp_path / "ws").repo_outline()
    assert results[0].rstrip().endswith("test_calculator_add; imports: calculator.py, mathlib/__init__.py")
    assert "  mathlib/operations.py:5 (function subtract)" in results[1]
    assert any(REPO_TOOLS_GUIDANCE.strip().splitlines()[0] in text for text in seen)


def test_dependency_cone_default_depth_and_find_tests(tmp_path):
    _, results, _ = _run(tmp_path, [_tc_compact("dependency_cone", {"target": "mathlib/operations.py"}), _tc_compact("find_tests", {"target": "mathlib/stats.py"})])
    assert results[0] == "mathlib/operations.py (file)\nIMPORTS:\n  (none)\nIMPORTED BY:\n  mathlib/__init__.py"
    assert results[1] == "mathlib/stats.py: tests\n  tests/test_core.py: test_mean, test_median_odd_length"


def test_repo_tools_absent_without_calibration(tmp_path):
    ctx, results, seen = _run(tmp_path, [_tc_compact("repo_outline", {})], config={})
    enum = ctx.plugins["schema_router"].get_model_tools()[0]["function"]["parameters"]["properties"]["tool"]["enum"]
    assert not set(enum) & {"repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone"}
    assert not any("Repository tools" in text for text in seen)
    assert "Unknown tool requested by model: repo_outline" in results[0]


def test_router_constraint_branches_for_repo_tools(tmp_path):
    ctx, _, _ = _run(tmp_path, [])
    branches = {b["properties"]["tool"]["const"]: b["properties"]["args"] for b in ctx.plugins["schema_router"].get_response_format()["anyOf"]}
    assert list(branches)[-6:] == ["repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone", "done"]
    assert branches["repo_outline"] == {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    assert branches["dependency_cone"]["properties"]["depth"] == {"type": "integer"}


def test_repo_tool_calls_do_not_mutate_or_count_as_reads(tmp_path):
    ctx, _, _ = _run(tmp_path, [_tc_compact("find_symbol", {"name": "subtract"})])
    loop = ctx.plugins["agent_loop"]
    assert loop._mutation_version == 0 and loop._successful_reads == set()


def test_file_tools_repo_tools_require_flag_and_validate_depth(tmp_path):
    shutil.copytree(MATHLIB, tmp_path / "ws", ignore=shutil.ignore_patterns("__pycache__"))
    tools = FileTools(tmp_path / "ws")
    with pytest.raises(ToolError, match="Unknown file tool"):
        tools.execute("repo_outline", {})
    tools.repo_tools = True
    assert "operations.py" in tools.execute("repo_outline", {})
    with pytest.raises(ToolError, match="depth must be an integer"):
        tools.execute("dependency_cone", {"target": "calculator.py", "depth": "deep"})
