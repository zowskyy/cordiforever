from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.grounding import targeted_grounding
from core.messages import Message
from core.outcomes import EscalationRequired
from core.path_candidates import declared_paths
from tests.test_agent import _build_agent_with_schema, _tc_compact

MATHLIB = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "mathlib"
L1 = {"targeted_grounding": True, "repo_tools": True}
L2 = {**L1, "evidence_gated_completion": True}


def _workspace(tmp_path) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(MATHLIB, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    return workspace


def _run(tmp_path, responses, calibration, request="subtract(5, 3) returns -2 but should return 2. Where is the bug?"):
    workspace = _workspace(tmp_path)
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    seen: list[str] = []
    events: list[tuple[str, dict]] = []
    model = ctx.plugins["ollama_model"]
    original = model.chat
    model.chat = lambda messages, tools: (seen.append("\n".join(m.content for m in messages)), original(messages, tools))[1]
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        return ctx.plugins["agent_loop"].run(request), seen, events
    finally:
        reg.stop_all()


def _done(summary: str) -> Message:
    return Message("assistant", "", tool_calls=[_tc_compact("done", {"summary": summary})])


def test_declared_paths_ignores_dotted_symbols():
    assert declared_paths("FILES: mathlib/operations.py, calculator.evaluate, subtract.js; SYMBOLS: a.b") == ["mathlib/operations.py", "subtract.js"]


def test_targeted_grounding_facts_and_evidence():
    lines, evidence = targeted_grounding(MATHLIB, "subtract(5, 3) is wrong; also check median.py")
    assert "- median.py: no such file; median: defined in mathlib/stats.py line 5; exported by mathlib/__init__.py" in lines
    assert "- subtract: defined in legacy/operations.py line 8, mathlib/operations.py line 5; exported by mathlib/__init__.py" in lines
    assert evidence == {"legacy/operations.py", "mathlib/operations.py", "mathlib/__init__.py", "mathlib/stats.py"}
    assert targeted_grounding(MATHLIB, "Say hello to everyone") == ([], set())


def test_l1_injects_grounding_before_first_call_without_gating(tmp_path):
    result, seen, events = _run(tmp_path, [_done("FILES: subtract.js")], L1)
    assert "Repository facts for names in the task:\n- subtract: defined in" in seen[0]
    assert result == "FILES: subtract.js"
    assert not [p for t, p in events if t == "done.rejected"]


def test_l2_rejects_invented_path_then_accepts_grounded_path(tmp_path):
    result, _, events = _run(tmp_path, [_done("FILES: subtract.js"), _done("FILES: mathlib/operations.py; SYMBOLS: subtract")], L2)
    assert result == "FILES: mathlib/operations.py; SYMBOLS: subtract"
    assert [p["paths"] for t, p in events if t == "done.rejected"] == [["subtract.js"]]


def test_l2_rejects_existing_but_unobserved_path_until_read(tmp_path):
    result, _, events = _run(tmp_path, [
        _done("FILES: calculator.py"),
        Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "calculator.py"})]),
        _done("FILES: calculator.py"),
    ], L2)
    assert result == "FILES: calculator.py"
    assert [p["paths"] for t, p in events if t == "done.rejected"] == [["calculator.py"]]


def test_l2_accepts_path_surfaced_by_repository_tool(tmp_path):
    result, _, events = _run(tmp_path, [
        Message("assistant", "", tool_calls=[_tc_compact("find_tests", {"target": "mathlib/stats.py"})]),
        _done("FILES: tests/test_core.py"),
    ], L2, request="Which test file covers stats?")
    assert result == "FILES: tests/test_core.py"
    assert not [t for t, _ in events if t == "done.rejected"]


def test_l2_second_unsupported_declaration_escalates(tmp_path):
    with pytest.raises(EscalationRequired) as raised:
        _run(tmp_path, [_done("FILES: index.js"), _done("FILES: index.js")], L2)
    assert raised.value.outcome.reason == "unsupported_declaration"
    assert raised.value.outcome.repeated_calls == ["index.js"]


def test_gate_without_grounding_still_requires_observation(tmp_path):
    result, _, events = _run(tmp_path, [_done("FILES: mathlib/operations.py"), Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "mathlib/operations.py"})]), _done("FILES: mathlib/operations.py")],
                             {"evidence_gated_completion": True})
    assert result == "FILES: mathlib/operations.py"
    assert len([t for t, _ in events if t == "done.rejected"]) == 1


def test_off_by_default(tmp_path):
    result, seen, events = _run(tmp_path, [_done("FILES: subtract.js")], {})
    assert result == "FILES: subtract.js"
    assert "Repository facts" not in seen[0]
    assert not [t for t, _ in events if t in ("done.rejected", "request.grounded")]
