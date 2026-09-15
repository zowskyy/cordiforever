"""qwen_evidence_v1 mechanism: a diagnosis may reference only a file read in full this run and unchanged since."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.messages import Message
from tests.test_agent import _build_agent_with_schema, _tc_compact

INVENTORY = Path(__file__).resolve().parents[1] / "benchmark" / "repos" / "inventory"
BASE = {"diagnose_before_mutation": True, "full_read_views": True}
RBE = {**BASE, "read_before_evidence": True}
EVIDENCE = "return sum(item.price for item in items)"


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _diag(path="inventory/service.py", evidence=EVIDENCE):
    return _call("diagnose", path=path, evidence=evidence, cause="ignores qty", change="multiply by qty")


def _run(tmp_path, responses, calibration, before_reply=None):
    workspace = tmp_path / "ws"
    shutil.copytree(INVENTORY, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = 12
    if before_reply is not None:
        model = ctx.plugins["ollama_model"]
        original = model.chat
        model.chat = lambda messages, tools: (before_reply(workspace, model.calls), original(messages, tools))[1]
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("total_value ignores quantities. Fix it.")
    finally:
        reg.stop_all()
    return workspace, events


def _rejections(events):
    return [(p["reason"], p.get("path")) for t, p in events if t == "guard.rejected"]


def _diagnose_results(events):
    """Outcomes of diagnose calls that reached the tool (the loop also emits a failed tool.result after a guard rejection)."""
    results, pending = [], False
    for t, p in events:
        if t == "guard.rejected" and p.get("tool") == "diagnose":
            pending = True
        elif t == "tool.result" and p.get("tool") == "diagnose":
            if pending:
                pending = False
            else:
                results.append(p["success"])
    return results


def test_pre_read_diagnosis_is_refused_and_allowed_after_a_full_read(tmp_path):
    _, events = _run(tmp_path, [_diag(), _call("read", path="inventory/service.py"), _diag(), _call("done", summary="x")], RBE)
    assert _rejections(events) == [("evidence_requires_read", "inventory/service.py")]
    assert _diagnose_results(events) == [True]
    refusal_text = [p["result"] for t, p in events if t == "tool.result" and p.get("tool") == "diagnose" and not p.get("success")]
    assert refusal_text and "Read inventory/service.py first" in refusal_text[0]


def test_diagnosis_refused_after_an_external_change_but_not_after_the_agents_own_write(tmp_path):
    fixed = (INVENTORY / "inventory" / "service.py").read_text(encoding="utf-8").replace("item.price for", "item.qty * item.price for")

    def external_edit(workspace, calls):
        if calls == 2:  # before the 3rd reply: someone else appends to the file after the read
            with (workspace / "inventory" / "service.py").open("a", encoding="utf-8") as handle:
                handle.write("\nEXTERNAL = 1\n")

    # The second diagnose quotes different text: an identical call would be dropped earlier by the duplicate-success filter.
    _, events = _run(tmp_path / "ext", [_call("read", path="inventory/service.py"), _diag(), _diag(evidence="def low_stock(items, threshold):"), _call("done", summary="x")],
                     RBE, before_reply=external_edit)
    assert _rejections(events) == [("evidence_requires_read", "inventory/service.py")]
    assert _diagnose_results(events) == [True]

    _, events = _run(tmp_path / "own", [
        _call("read", path="inventory/service.py"), _diag(),
        _call("write", path="inventory/service.py", content=fixed),
        _diag(evidence="item.qty * item.price"), _call("done", summary="x"),
    ], RBE)
    assert _rejections(events) == [] and _diagnose_results(events) == [True, True]


def test_partial_read_does_not_satisfy_the_prerequisite(tmp_path):
    # Without full_read_views the compact preview truncates the 277-char file, so the read is not "in full".
    _, events = _run(tmp_path, [_call("read", path="inventory/service.py"), _diag(), _call("done", summary="x")],
                     {"diagnose_before_mutation": True, "read_before_evidence": True})
    assert _rejections(events) == [("evidence_requires_read", "inventory/service.py")]
    assert _diagnose_results(events) == []


def test_verbatim_check_is_unchanged_after_the_read(tmp_path):
    _, events = _run(tmp_path, [_call("read", path="inventory/service.py"), _diag(evidence="return sum(item.qty * item.cost)"), _call("done", summary="x")], RBE)
    assert _rejections(events) == []
    assert _diagnose_results(events) == [False]


def test_off_by_default_pre_read_diagnosis_executes(tmp_path):
    _, events = _run(tmp_path, [_diag(), _call("done", summary="x")], BASE)
    assert _rejections(events) == [] and _diagnose_results(events) == [True]


def test_refusal_text_names_only_the_requested_path(tmp_path):
    _, events = _run(tmp_path, [_diag(path="inventory/__init__.py", evidence="from inventory.service import"), _call("done", summary="x")], RBE)
    text = json.dumps([p for t, p in events if t == "guard.rejected"])
    assert "service.py" not in text.replace("inventory/__init__.py", "")
