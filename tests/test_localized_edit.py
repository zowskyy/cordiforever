"""qwen_localedit_v1 mechanism: bounded edit of one Python definition or one JSON value; no full rewrites of existing files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.messages import Message
from core.structured_edit import EditError, replace_python_symbol, set_json_pointer_value
from tests.test_agent import _build_agent_with_schema, _tc_compact

REPOS = Path(__file__).resolve().parents[1] / "benchmark" / "repos"
EXTRACT = {"diagnose_before_mutation": True, "full_read_views": True, "read_before_evidence": True, "evidence_extraction": True,
           "require_read_before_write": True}
LOCAL = {**EXTRACT, "localized_edits": True}
SERVICE = (REPOS / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
APP_JSON = (REPOS / "configsvc" / "config" / "app.json").read_text(encoding="utf-8")


def test_replace_python_symbol_keeps_unrelated_definitions():
    new, span = replace_python_symbol("s.py", SERVICE, "total_value", "def total_value(items):\n    return sum(item.qty * item.price for item in items)\n")
    assert span == (4, 5)
    assert "return sum(item.qty * item.price for item in items)" in new
    for kept in ("REORDER_THRESHOLD = 10", "def low_stock(items, threshold):", "def find_item(items, sku):"):
        assert kept in new
    assert new.endswith("\n") and new.count("def total_value") == 1


def test_replace_python_symbol_method_reindent_and_new_helper():
    text = "class Store:\n    def total(self):\n        return 0\n\n    def other(self):\n        return 1\n"
    new, _ = replace_python_symbol("s.py", text, "Store.total", "def total(self):\n    return 42\n")
    assert "    def total(self):\n        return 42\n" in new and "def other(self)" in new
    new, _ = replace_python_symbol("s.py", SERVICE, "find_item", "def find_item(items, sku):\n    return next((i for i in items if i.sku == sku), None)\n\n\ndef has_item(items, sku):\n    return find_item(items, sku) is not None\n")
    assert "def has_item" in new and "def low_stock" in new
    new, _ = replace_python_symbol("s.py", SERVICE, "REORDER_THRESHOLD", "REORDER_THRESHOLD = 5")
    assert new.startswith("REORDER_THRESHOLD = 5\n")


@pytest.mark.parametrize("target,replacement,message", [
    ("total", "def total(items):\n    return 0\n", "is not a function, class, method or assignment defined in s.py"),
    ("total_value", "def total_worth(items):\n    return 0\n", "replacement must define total_value"),
    ("total_value", "def total_value(items):\n    return 0\n\ndef low_stock(items, t):\n    return []\n", "also redefines low_stock"),
    ("total_value", "def total_value(items)\n    return 0\n", "replacement is not valid Python"),
    ("total_value", "   ", "replacement must be non-empty"),
])
def test_replace_python_symbol_refusals(target, replacement, message):
    with pytest.raises(EditError) as raised:
        replace_python_symbol("s.py", SERVICE, target, replacement)
    assert message in str(raised.value)
    for name in ("find_item", "REORDER_THRESHOLD") if "low_stock" in message else ():
        assert name not in str(raised.value)


def test_set_json_pointer_value_preserves_other_keys_and_format():
    new, change = set_json_pointer_value("app.json", APP_JSON, "/database/host", '"db.internal"')
    doc = json.loads(new)
    assert doc["database"] == {"host": "db.internal", "port": 5432} and doc["name"] == "svc" and doc["port"] == 3000
    assert new.endswith("\n") and '\n  "database": {\n    "host": "db.internal",' in new
    assert change == '/database/host: "localhost" -> "db.internal"'
    new, _ = set_json_pointer_value("app.json", APP_JSON, "/features", '["login", "search"]')
    assert json.loads(new)["features"] == ["login", "search"]


@pytest.mark.parametrize("pointer,replacement,message", [
    ("/database/user", '"x"', "is not a JSON pointer that resolves"),
    ("port", "8080", "is not a JSON pointer that resolves"),
    ("/", "{}", "is not a JSON pointer that resolves"),
    ("/port", '"8080"', "refusing to replace it with a string"),
    ("/port", "eight", "replacement must be a JSON value"),
])
def test_set_json_pointer_value_refusals(pointer, replacement, message):
    with pytest.raises(EditError) as raised:
        set_json_pointer_value("app.json", APP_JSON, pointer, replacement)
    assert message in str(raised.value)


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _run(tmp_path, responses, calibration, repo="inventory"):
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / repo, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = 12
    model = ctx.plugins["ollama_model"]
    original = model.chat
    sent: list[str] = []
    model.chat = lambda messages, tools: (sent.append("\n".join(m.content or "" for m in messages)), original(messages, tools))[1]
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("total_value ignores quantities. Fix it.")
        tools = {b["properties"]["tool"]["const"] for b in ctx.plugins["schema_router"].get_response_format()["anyOf"]}
    finally:
        reg.stop_all()
    return workspace, events, sent, tools


FIX = "def total_value(items):\n    return sum(item.qty * item.price for item in items)\n"


def _results(events, tool):
    return [p for t, p in events if t == "tool.result" and p.get("tool") == tool]


def test_edit_after_read_and_diagnosis_changes_only_the_symbol(tmp_path):
    workspace, events, sent, tools = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="ignores qty", change="multiply"),
        _call("edit", path="inventory/service.py", target="total_value", replacement=FIX),
        _call("done", summary="fixed"),
    ], LOCAL)
    assert _results(events, "edit_symbol")[0]["success"] is True
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == SERVICE.replace(
        "return sum(item.price for item in items)", "return sum(item.qty * item.price for item in items)")
    guidance = json.loads(sent[0].split("\n", 1)[0])["content"] if sent[0].startswith("{") else sent[0]
    assert "edit" in tools and "- write: {\"path\": \"file\", \"content\": \"full file text\"} - create a NEW file" in guidance
    assert "create or overwrite a file" not in guidance and "- edit: {\"path\": \"<file>\", \"target\":" in guidance


def test_write_to_existing_file_is_refused_new_file_allowed(tmp_path):
    workspace, events, _, _ = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="c", change="x"),
        _call("write", path="inventory/service.py", content=FIX),
        _call("write", path="notes.txt", content="hello"),
        _call("done", summary="x"),
    ], LOCAL)
    assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["overwrite_existing_file"]
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == SERVICE
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello"


def test_edit_passes_through_mutation_guards(tmp_path):
    _, events, _, _ = _run(tmp_path, [
        _call("edit", path="inventory/service.py", target="total_value", replacement=FIX),
        _call("read", path="inventory/service.py"),
        _call("edit", path="inventory/service.py", target="total_value", replacement=FIX + "\n"),
        _call("done", summary="x"),
    ], LOCAL)
    assert [p["reason"] for t, p in events if t == "guard.rejected"] == ["diagnosis_required", "diagnosis_required"]
    assert not [p for p in _results(events, "edit_symbol") if p["success"]]


def test_json_edit_through_the_loop(tmp_path):
    workspace, events, _, _ = _run(tmp_path, [
        _call("read", path="config/app.json"),
        _call("diagnose", path="config/app.json", target="/database/host", cause="wrong host", change="set db.internal"),
        _call("edit", path="config/app.json", target="/database/host", replacement='"db.internal"'),
        _call("done", summary="x"),
    ], LOCAL, repo="configsvc")
    doc = json.loads((workspace / "config" / "app.json").read_text(encoding="utf-8"))
    assert doc["database"]["host"] == "db.internal" and doc["name"] == "svc" and doc["features"] == ["login"]


def test_edit_errors_give_no_suggestions(tmp_path):
    _, events, _, _ = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="c", change="x"),
        _call("edit", path="inventory/service.py", target="totalvalue", replacement=FIX),
        _call("done", summary="x"),
    ], LOCAL)
    payload = [p for p in _results(events, "edit_symbol") if not p["success"]][0]["result"]
    failure = json.loads(payload)["error"]  # the loop's error text, excluding the echoed model arguments
    assert "totalvalue is not a function, class, method or assignment defined in inventory/service.py" in failure
    for name in ("total_value", "low_stock", "find_item", "REORDER_THRESHOLD"):
        assert name not in failure


def test_control_arm_has_no_edit_and_may_overwrite(tmp_path):
    fixed = SERVICE.replace("item.price for", "item.qty * item.price for")
    workspace, events, sent, tools = _run(tmp_path, [
        _call("read", path="inventory/service.py"),
        _call("diagnose", path="inventory/service.py", target="total_value", cause="c", change="x"),
        _call("write", path="inventory/service.py", content=fixed),
        _call("done", summary="x"),
    ], EXTRACT)
    guidance = json.loads(sent[0].split("\n", 1)[0])["content"] if sent[0].startswith("{") else sent[0]
    assert "edit" not in tools and "create or overwrite a file" in guidance and "- edit:" not in guidance
    assert not [t for t, _ in events if t == "guard.rejected"]
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == fixed
