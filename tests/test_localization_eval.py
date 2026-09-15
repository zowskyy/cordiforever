from __future__ import annotations

from pathlib import Path

from benchmark import localization_eval as le
from benchmark.repo_tasks import TASKS_BY_NAME
from core.bounded_task import snapshot
from core.messages import Message
from core.repo_index import RepositoryIndex
from tests.test_agent import _build_agent_with_schema, _tc_compact

MATHLIB = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "mathlib"


def test_levels_differ_only_in_grounding_and_gate():
    c = le.CONDITIONS
    assert set(c) == {f"{m}_{lvl}" for m in ("gemma", "qwen") for lvl in ("L0", "L1", "L2")}
    for level in ("L0", "L1", "L2"):
        assert c[f"gemma_{level}"]["overrides"] == c[f"qwen_{level}"]["overrides"]

    def diff(a, b):
        return {k for k in set(c[a]["overrides"]) | set(c[b]["overrides"]) if c[a]["overrides"].get(k) != c[b]["overrides"].get(k)}

    assert diff("gemma_L0", "gemma_L1") == {"targeted_grounding"}
    assert diff("gemma_L1", "gemma_L2") == {"evidence_gated_completion"}
    assert all(cfg["overrides"]["navigation_only"] and cfg["overrides"]["repo_tools"] for cfg in c.values())


def test_unsupported_declarations_use_independent_evidence():
    task = TASKS_BY_NAME["mathlib_fix_subtract"]
    index = RepositoryIndex(MATHLIB)
    timeline = [
        ("request.grounded", {"evidence": ["mathlib/operations.py"]}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "calculator.py"}, "success": True}),
        ("tool.result", {"tool": "find_tests", "arguments": {"target": "x"}, "success": True, "result": "x: tests\n  tests/test_core.py: test_add"}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "mathlib/stats.py"}, "success": False}),
    ]
    scores = le.score_task(task, "FILES: mathlib/operations.py, calculator.py, tests/test_core.py, mathlib/stats.py, subtract.js",
                           timeline, set(index.files), index, [])
    assert scores["unsupported_declared_files"] == ["mathlib/stats.py", "subtract.js"]


def test_template_renders_task_and_literal_json():
    text = le.LOCALIZE_TEMPLATE.format(prompt="Fix subtract.")
    assert text.startswith("Task: Fix subtract.") and '{"tool": "done", "args": {"summary": "FILES:' in text


def test_parse_declaration_with_and_without_symbols_section():
    index = RepositoryIndex(MATHLIB)
    files, symbols = le.parse_declaration("FILES: mathlib/operations.py, calculator.py; SYMBOLS: subtract, calculator.evaluate", index)
    assert files == ["mathlib/operations.py", "calculator.py"] and symbols == ["subtract", "evaluate"]
    files, symbols = le.parse_declaration("The bug is in mathlib/operations.py in subtract.", index)
    assert files == ["mathlib/operations.py"] and symbols == ["subtract"]
    assert le.parse_declaration("", index) == ([], [])
    assert le.parse_declaration("FILES: mathlib/stats.py; SYMBOLS: calculator.evaluate", index) == (["mathlib/stats.py"], ["evaluate"])


def _invoked(tool, **args):
    return ("tool.invoked", {"tool_name": tool, "arguments": args})


def test_score_task_metrics():
    task = TASKS_BY_NAME["mathlib_fix_subtract"]
    index = RepositoryIndex(MATHLIB)
    timeline = [
        _invoked("read_file", path="median.py"),
        _invoked("find_symbol", name="subtract.py"),
        _invoked("find_symbol", name="subtract"),
        _invoked("read_file", path="calculator.py"),
        _invoked("read_file", path="mathlib/operations.py"),
        _invoked("list_directory", path="mathlib"),
        ("guard.rejected", {"reason": "navigation_only"}),
    ]
    scores = le.score_task(task, "FILES: mathlib/operations.py, legacy/operations.py, ghost.py; SYMBOLS: subtract, frobnicate",
                           timeline, set(index.files), index, [None, "not_json", None])
    assert scores["file_recall"] == 1.0 and scores["file_precision"] == round(1 / 3, 3)
    assert scores["symbol_recall"] == 1.0 and scores["symbol_precision"] == 0.5
    assert scores["declared_invented_files"] == ["ghost.py"] and scores["declared_unknown_symbols"] == ["frobnicate"]
    assert scores["touched_files"] == ["calculator.py", "mathlib/operations.py"] and scores["first_gold_rank"] == 1
    assert (scores["path_calls"], scores["invented_path_calls"]) == (5, 2)
    assert scores["protocol_failures"] == 2 and scores["write_attempts"] == 1


def test_no_declaration_scores_zero_recall_and_no_precision():
    task = TASKS_BY_NAME["mathlib_fix_subtract"]
    index = RepositoryIndex(MATHLIB)
    scores = le.score_task(task, "", [], set(index.files), index, [])
    assert scores["declaration_present"] is False and scores["file_recall"] == 0.0 and scores["file_precision"] is None


def test_navigation_only_refuses_writes_and_constraint_excludes_them(tmp_path):
    import shutil

    workspace = tmp_path / "ws"
    shutil.copytree(MATHLIB, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    before = snapshot(workspace)
    ctx, reg = _build_agent_with_schema(workspace, [
        Message("assistant", "", tool_calls=[_tc_compact("write", {"path": "notes.txt", "content": "x"})]),
        Message("assistant", "", tool_calls=[_tc_compact("find_symbol", {"name": "subtract"})]),
        Message("assistant", "done"),
    ], profile="lite", compact_schema=True, config={"calibration": {"navigation_only": True, "repo_tools": True}})
    events = []
    ctx.events.on("guard.rejected", lambda e: events.append(e.payload["reason"]))
    try:
        ctx.plugins["agent_loop"].run("locate subtract")
        tools = [b["properties"]["tool"]["const"] for b in ctx.plugins["schema_router"].get_response_format()["anyOf"]]
    finally:
        reg.stop_all()
    assert events == ["navigation_only"]
    after = {k: v for k, v in snapshot(workspace).items() if k != "test.db"}  # the test helper's event log lives in the workspace
    assert after == before
    assert set(tools) == {"read", "list", "repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone", "done"}
