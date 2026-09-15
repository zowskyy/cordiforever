"""qwen_selectorkind_v1 mechanism: explicit selector kind routed to the unchanged resolvers, with no normalization."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.messages import Message
from tests.test_agent import _build_agent_with_schema, _tc_compact

REPOS = Path(__file__).resolve().parents[1] / "benchmark" / "repos"
LOCAL = {"diagnose_before_mutation": True, "full_read_views": True, "read_before_evidence": True, "evidence_extraction": True,
         "require_read_before_write": True, "localized_edits": True}
KIND = {**LOCAL, "explicit_selector_kind": True}
SERVICE = (REPOS / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
FIX = "def total_value(items):\n    return sum(item.qty * item.price for item in items)\n"


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _run(tmp_path, edit_args, calibration, repo="inventory", read="inventory/service.py", diag_target="total_value"):
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / repo, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    responses = [
        _call("read", path=read),
        _call("diagnose", path=read, target=diag_target, cause="c", change="x"),
        _call("edit", **edit_args),
        _call("done", summary="x"),
    ]
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
        branch = [b for b in ctx.plugins["schema_router"].get_response_format()["anyOf"] if b["properties"]["tool"]["const"] == "edit"][0]
    finally:
        reg.stop_all()
    edits = [p for t, p in events if t == "tool.result" and p.get("tool") == "edit_symbol"]
    guidance = json.loads(sent[0].split("\n", 1)[0])["content"]
    return workspace, edits, guidance, branch


def _error(edit):
    return json.loads(edit["result"])["error"]


def test_python_symbol_kind_edits_through_the_existing_resolver(tmp_path):
    workspace, edits, guidance, branch = _run(tmp_path, {"path": "inventory/service.py", "selector_kind": "python_symbol", "target": "total_value", "replacement": FIX}, KIND)
    assert edits[0]["success"] is True
    assert "return sum(item.qty * item.price for item in items)" in (workspace / "inventory" / "service.py").read_text(encoding="utf-8")
    args = branch["properties"]["args"]
    assert args["required"] == ["path", "selector_kind", "target", "replacement"]
    assert args["properties"]["selector_kind"] == {"type": "string", "enum": ["python_symbol", "json_pointer"]}
    assert "\"selector_kind\": \"python_symbol\", \"target\": \"<function or class name>\"" in guidance
    assert "\"selector_kind\": \"json_pointer\", \"target\": \"</key/subkey>\"" in guidance
    assert "JSON pointer such as /key in a .json file" not in guidance


def test_no_normalization_of_slash_prefixed_python_targets(tmp_path):
    workspace, edits, _, _ = _run(tmp_path, {"path": "inventory/service.py", "selector_kind": "python_symbol", "target": "/total_value", "replacement": FIX}, KIND)
    assert edits[0]["success"] is False
    assert "/total_value is not a function, class, method or assignment defined in inventory/service.py" in _error(edits[0])
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == SERVICE


def test_kind_must_match_file_type_and_is_never_inferred(tmp_path):
    workspace, edits, _, _ = _run(tmp_path, {"path": "inventory/service.py", "selector_kind": "json_pointer", "target": "total_value", "replacement": FIX}, KIND)
    assert edits[0]["success"] is False and _error(edits[0]) == "selector_kind json_pointer does not apply to inventory/service.py."
    assert (workspace / "inventory" / "service.py").read_text(encoding="utf-8") == SERVICE

    workspace, edits, _, _ = _run(tmp_path / "json", {"path": "config/app.json", "selector_kind": "python_symbol", "target": "/port", "replacement": "8080"},
                                  KIND, repo="configsvc", read="config/app.json", diag_target="/port")
    assert edits[0]["success"] is False and _error(edits[0]) == "selector_kind python_symbol does not apply to config/app.json."


def test_json_pointer_kind_edits_json(tmp_path):
    workspace, edits, _, _ = _run(tmp_path, {"path": "config/app.json", "selector_kind": "json_pointer", "target": "/port", "replacement": "8080"},
                                  KIND, repo="configsvc", read="config/app.json", diag_target="/port")
    assert edits[0]["success"] is True
    assert json.loads((workspace / "config" / "app.json").read_text(encoding="utf-8"))["port"] == 8080


def test_control_arm_edit_unchanged(tmp_path):
    workspace, edits, guidance, branch = _run(tmp_path, {"path": "inventory/service.py", "target": "total_value", "replacement": FIX}, LOCAL)
    assert edits[0]["success"] is True
    assert "selector_kind" not in branch["properties"]["args"]["properties"]
    assert "selector_kind" not in guidance and "JSON pointer such as /key in a .json file" in guidance
