"""qwen_extract_v1 mechanism: the model names a selector; the span is extracted from the frozen read snapshot only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.diagnosis import json_pointer_span, python_symbol_span, target_line_span
from core.messages import Message
from tests.test_agent import _build_agent_with_schema, _tc_compact

REPOS = Path(__file__).resolve().parents[1] / "benchmark" / "repos"
ARMS = {"diagnose_before_mutation": True, "full_read_views": True, "read_before_evidence": True}
EXTRACT = {**ARMS, "evidence_extraction": True}
APP_JSON = '{\n  "name": "svc",\n  "port": 3000,\n  "database": {\n    "host": "localhost",\n    "port": 5432\n  },\n  "features": [\n    "login"\n  ]\n}\n'


def test_python_symbol_span_exact_names_only():
    text = "X = 1\n\n\nclass Store:\n    def total(self):\n        return 0\n\n\ndef total_value(items):\n    return sum(i.price for i in items)\n"
    assert python_symbol_span(text, "total_value") == (9, 10)
    assert python_symbol_span(text, "Store") == (4, 6)
    assert python_symbol_span(text, "Store.total") == (5, 6)
    assert python_symbol_span(text, "X") == (1, 1)
    for miss in ("total", "total_valu", "Total_value", "return sum", "def total_value(items):", "Store.missing"):
        assert python_symbol_span(text, miss) is None
    assert python_symbol_span("def broken(:\n", "broken") is None


def test_json_pointer_span_requires_full_resolution():
    assert json_pointer_span(APP_JSON, "/port") == (3, 3)
    assert json_pointer_span(APP_JSON, "/database/port") == (6, 6)  # nested key, not the top-level "port"
    assert json_pointer_span(APP_JSON, "/database/host") == (5, 5)
    assert json_pointer_span(APP_JSON, "/features/0") == (8, 8)  # array index -> enclosing key line
    for miss in ("port", "/database/user", "/features/3", "/features/x", "", "/nope"):
        assert json_pointer_span(APP_JSON, miss) is None
    assert json_pointer_span('[\n  {"sku": "A", "qty": 1}\n]\n', "/0/qty") is None  # root array: no enclosing key
    assert target_line_span("notes.md", "anything", "x") is None


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _run(tmp_path, responses, calibration, repo="inventory", on_reply=None):
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / repo, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = 12
    model = ctx.plugins["ollama_model"]
    original = model.chat
    sent: list[str] = []

    def chat(messages, tools):
        if on_reply is not None:
            on_reply(workspace, model.calls)
        sent.append("\n".join(m.content or "" for m in messages))
        return original(messages, tools)

    model.chat = chat
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("total_value ignores quantities. Fix it.")
        tools = [b for b in ctx.plugins["schema_router"].get_response_format()["anyOf"] if b["properties"]["tool"]["const"] == "diagnose"]
    finally:
        reg.stop_all()
    return workspace, events, sent, tools


def _diag_results(events):
    return [p for t, p in events if t == "tool.result" and p.get("tool") == "diagnose"]


def test_extraction_returns_the_snapshot_span_and_unlocks_mutation(tmp_path):
    seed = (REPOS / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
    fixed = seed.replace("item.price for", "item.qty * item.price for")
    workspace, events, sent, tools = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="ignores qty", change="multiply by qty"),
        _call("write", path="inventory/service.py", content=fixed),
        _call("done", summary="x"),
    ], EXTRACT)
    result = _diag_results(events)[0]
    assert result["success"] is True
    assert result["result"].startswith("Diagnosis recorded for inventory/service.py (lines 4-5):\ndef total_value(items):\n    return sum(item.price for item in items)\n")
    assert "snapshot_sha256: " in result["result"]
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == fixed
    assert tools[0]["properties"]["args"]["required"] == ["path", "target", "cause", "change"]
    assert "evidence" not in tools[0]["properties"]["args"]["properties"]
    assert "the function or class name in a .py file, or the JSON pointer" in sent[0]


def test_selector_miss_fails_without_suggestions(tmp_path):
    _, events, _, _ = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="return sum(item.price for item in items)", cause="c", change="x"),
        _call("done", summary="x"),
    ], EXTRACT)
    result = _diag_results(events)[-1]
    assert result["success"] is False
    assert "is not a function, class, method or assignment defined in inventory/service.py as you read it" in result["result"]
    for name in ("total_value", "low_stock", "find_item", "REORDER_THRESHOLD"):
        assert name not in result["result"].replace("return sum(item.price for item in items)", "")


def test_extraction_uses_the_read_snapshot_not_disk(tmp_path):
    # After the read the file changes on disk, then the agent writes it itself (fingerprint accepted), and the snapshot
    # is still what the model saw.
    seed = (REPOS / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
    renamed = seed.replace("def total_value", "def total_worth")
    workspace, events, _, _ = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="low_stock", cause="c", change="x"),
        _call("write", path="inventory/service.py", content=renamed),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="c", change="y"),
        _call("done", summary="x"),
    ], EXTRACT)
    assert "def total_worth" in (workspace / "inventory" / "service.py").read_text(encoding="utf-8")
    results = _diag_results(events)
    assert [r["success"] for r in results] == [True, True]
    assert "def total_value(items):" in results[-1]["result"]  # resolved in the read snapshot, not the file on disk


def test_no_complete_read_means_no_extraction(tmp_path):
    # Without full_read_views the 277-char file is truncated: read-before-evidence refuses first (control guard kept).
    _, events, _, _ = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="c", change="x"),
        _call("done", summary="x"),
    ], {**EXTRACT, "full_read_views": False})
    assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["evidence_requires_read"]


def test_json_pointer_extraction_through_the_loop(tmp_path):
    _, events, _, _ = _run(tmp_path, [
        _call("read", path="config/app.json"),
        _call("diagnose", path="config/app.json", target="/port", cause="wrong port", change="set 8080"),
        _call("done", summary="x"),
    ], EXTRACT, repo="configsvc")
    result = _diag_results(events)[0]
    assert result["success"] is True and '"port": 3000' in result["result"].splitlines()[1]


def test_control_arm_unchanged(tmp_path):
    _, events, sent, tools = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", evidence="return sum(item.price for item in items)", cause="c", change="x"),
        _call("done", summary="x"),
    ], ARMS)
    assert _diag_results(events)[0]["success"] is True
    assert tools[0]["properties"]["args"]["required"] == ["path", "evidence", "cause", "change"]
    assert "exact lines copied from the file" in sent[0] and "JSON pointer" not in sent[0]
