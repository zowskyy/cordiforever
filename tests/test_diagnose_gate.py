from __future__ import annotations

import shutil
from pathlib import Path

from core.diagnosis import evidence_line_span
from core.messages import Message
from tests.test_agent import _build_agent_with_schema, _tc_compact

INVENTORY = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "inventory"
DIAG = {"diagnose_before_mutation": True}


def _workspace(tmp_path) -> Path:
    workspace = tmp_path / "ws"
    shutil.copytree(INVENTORY, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    return workspace


def _run(tmp_path, responses, calibration):
    workspace = _workspace(tmp_path)
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    seen: list[str] = []
    events: list[tuple[str, dict]] = []
    model = ctx.plugins["ollama_model"]
    original = model.chat
    model.chat = lambda messages, tools: (seen.append("\n".join(m.content for m in messages)), original(messages, tools))[1]
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    ctx.plugins["agent_loop"].max_rounds = 12  # helper default is 3; scripted runs here take up to 7 rounds
    try:
        ctx.plugins["agent_loop"].run("total_value ignores quantities. Fix it.")
        tools = [b["properties"]["tool"]["const"] for b in ctx.plugins["schema_router"].get_response_format()["anyOf"]]
    finally:
        reg.stop_all()
    return workspace, seen, events, tools


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


FIXED = "REORDER_THRESHOLD = 10\n\n\ndef total_value(items):\n    return sum(item.price * item.qty for item in items)\n"


def test_evidence_line_span_exact_reflowed_short_absent():
    text = "a = 1\n\ndef total_value(items):\n    return sum(item.price for item in items)\n"
    assert evidence_line_span(text, "return sum(item.price for item in items)") == (4, 4)
    assert evidence_line_span(text, "def total_value(items):   return   sum(item.price") == (3, 4)
    assert evidence_line_span(text, "a = 1") is None  # 3 non-space characters
    assert evidence_line_span(text, "return sum(item.qty)") is None


def test_diagnose_tool_and_full_reads_only_with_calibration(tmp_path):
    long_read = [_call("read", path="inventory/service.py"), _call("done", summary="x")]
    _, seen, events, tools = _run(tmp_path / "a", list(long_read), {"full_read_views": True, **DIAG})
    shown = [p["result"] for t, p in events if t == "tool.result" and p.get("tool") == "read_file"]
    assert shown == [(INVENTORY / "inventory" / "service.py").read_text(encoding="utf-8")]
    assert "diagnose" in tools and "Before changing an existing file, first send diagnose" in seen[0]

    _, seen, events, tools = _run(tmp_path / "b", list(long_read), {})
    shown = [p["result"] for t, p in events if t == "tool.result" and p.get("tool") == "read_file"]
    assert len(shown[0]) == 203 and shown[0].endswith("...")
    assert "diagnose" not in tools and "send diagnose" not in seen[0]


def test_mutation_of_existing_file_requires_diagnosis_for_that_path(tmp_path):
    workspace, _, events, _ = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("write", path="inventory/service.py", content=FIXED),
        _call("diagnose", path="inventory/__init__.py", evidence="from inventory.service import", cause="c", change="x"),
        _call("write", path="inventory/service.py", content=FIXED),
        _call("diagnose", path="inventory/service.py", evidence="return sum(item.price for item in items)", cause="ignores qty", change="multiply by qty"),
        _call("write", path="inventory/service.py", content=FIXED),
        _call("done", summary="fixed"),
    ], {"full_read_views": True, **DIAG})
    assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["diagnosis_required", "diagnosis_required"]
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == FIXED
    results = [(p["tool"], p["success"]) for t, p in events if t == "tool.result" and "tool" in p]
    assert ("diagnose", True) in results


def test_diagnosis_with_evidence_not_in_file_fails_and_does_not_unlock(tmp_path):
    workspace, _, events, _ = _run(tmp_path, [
        _call("diagnose", path="inventory/service.py", evidence="return sum(item.qty * item.cost)", cause="c", change="x"),
        _call("write", path="inventory/service.py", content=FIXED),
        _call("done", summary="x"),
    ], DIAG)
    diag = [p for t, p in events if t == "tool.result" and p.get("tool") == "diagnose"]
    assert diag and diag[0]["success"] is False and "not text from inventory/service.py" in diag[0]["result"]
    assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["diagnosis_required"]
    assert FIXED not in (workspace / "inventory" / "service.py").read_text(encoding="utf-8")


def test_new_files_need_no_diagnosis_and_gate_is_off_by_default(tmp_path):
    workspace, _, events, _ = _run(tmp_path / "a", [_call("write", path="notes.txt", content="hi"), _call("done", summary="x")], DIAG)
    assert (workspace / "notes.txt").is_file() and not [t for t, _ in events if t == "guard.rejected"]

    workspace, _, events, _ = _run(tmp_path / "b", [_call("write", path="inventory/service.py", content=FIXED), _call("done", summary="x")], {})
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == FIXED
    assert not [t for t, _ in events if t == "guard.rejected"]
