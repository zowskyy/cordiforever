"""Harness invariant: guidance after a filtered duplicate call must describe what actually happened.

Defect (2026-09-14, EXPERIMENT_LOG "the harness tells the model to stop after a repeated read"): a repeated successful
read was answered with "You already completed the requested task successfully ... Finish now", and 1B models then
declared done without changing anything.
"""

from __future__ import annotations

import pytest

from core.messages import Message
from core.outcomes import EscalationRequired
from tests.test_agent import _build_agent_with_schema, _tc_compact, build_agent, tc

COMPLETED = "completed the requested task successfully"


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _run(tmp_path, responses, calibration=None, max_rounds=12):
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    ctx, reg = _build_agent_with_schema(tmp_path, responses, profile="lite", compact_schema=True, config={"calibration": calibration or {}})
    ctx.plugins["agent_loop"].max_rounds = max_rounds
    sent: list[str] = []
    model = ctx.plugins["ollama_model"]
    original = model.chat
    model.chat = lambda messages, tools: (sent.append("\n".join(m.content or "" for m in messages)), original(messages, tools))[1]
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        return ctx.plugins["agent_loop"].run("Count the lines in notes.txt and write the count to count.txt"), sent, events
    finally:
        reg.stop_all()


def test_repeated_read_never_claims_completion(tmp_path):
    result, sent, events = _run(tmp_path, [
        _call("read", path="notes.txt"),
        _call("read", path="notes.txt"),
        _call("write", path="count.txt", content="2"),
        _call("done", summary="wrote 2"),
    ])
    assert result == "wrote 2"
    assert COMPLETED not in sent[2]
    assert "You already ran read_file notes.txt and the result is shown above" in sent[2] and "The task is not finished" in sent[2]
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "2"
    assert [p["tool"] for t, p in events if t == "tool.result" and p.get("success")] == ["read_file", "write_file"]


def test_repeated_write_behavior_unchanged(tmp_path):
    call = tc("write_file", {"path": "a.txt", "content": "hi"})
    ctx, reg = build_agent(tmp_path, [Message("assistant", "", tool_calls=[call]), Message("assistant", "", tool_calls=[call]), Message("assistant", "already done")])
    sent: list[str] = []
    model = ctx.plugins["ollama_model"]
    original = model.chat
    model.chat = lambda messages, tools: (sent.append("\n".join(m.content or "" for m in messages)), original(messages, tools))[1]
    try:
        assert ctx.plugins["agent_loop"].run("hi") == "already done"
    finally:
        reg.stop_all()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hi"
    assert COMPLETED in sent[2]


def test_mixed_reply_keeps_the_legitimate_call(tmp_path):
    mixed = Message("assistant", "", tool_calls=[_tc_compact("read", {"path": "notes.txt"}), _tc_compact("write", {"path": "count.txt", "content": "2"})])
    result, sent, events = _run(tmp_path, [_call("read", path="notes.txt"), mixed, _call("done", summary="ok")])
    assert result == "ok"
    assert (tmp_path / "count.txt").read_text(encoding="utf-8") == "2"
    assert [p["tool"] for t, p in events if t == "tool.result" and p.get("success")] == ["read_file", "write_file"]
    assert not any(COMPLETED in s or "You already ran" in s for s in sent)


def test_reread_after_a_change_is_executed_not_filtered(tmp_path):
    result, sent, events = _run(tmp_path, [
        _call("read", path="notes.txt"),
        _call("write", path="count.txt", content="2"),
        _call("read", path="notes.txt"),
        _call("done", summary="ok"),
    ])
    assert result == "ok"
    assert [p["tool"] for t, p in events if t == "tool.result" and p.get("success")] == ["read_file", "write_file", "read_file"]
    assert not any("You already ran" in s for s in sent)


def test_reread_loop_is_bounded_by_the_repeat_policy(tmp_path):
    # The 1B preset's repeat policy: the third identical read is a failed repeat; the scripted model has no sampling
    # options, so the loop escalates instead of re-reading until max_rounds.
    responses = [_call("read", path="notes.txt") for _ in range(12)]
    with pytest.raises(EscalationRequired) as raised:
        _run(tmp_path, responses, calibration={"repeat_retry_temperature": 0.4})
    assert raised.value.outcome.reason == "repeat_retry_unavailable"
    assert raised.value.outcome.round <= 4


def test_repo_task_replay_no_longer_injects_false_completion(monkeypatch):
    """Independent replay of the traced Gemma trajectory through the evaluator's production wiring."""
    from benchmark import repo_task_eval as rte
    from benchmark.repo_tasks import TASKS_BY_NAME

    script = ['{"tool": "read", "args": {"path": "inventory/service.py"}}'] * 2 + ['{"tool": "done", "args": {"summary": "x"}}']
    sent: list[str] = []
    real_build = rte.build_application

    def scripted_build(*args, **kwargs):
        ctx, reg = real_build(*args, **kwargs)
        model = ctx.plugins["ollama_model"]
        model.chat = lambda messages, tools: (sent.append("\n".join(m.content or "" for m in messages)), Message("assistant", script.pop(0)))[1]
        model.last_done_reason = "stop"
        return ctx, reg

    monkeypatch.setattr(rte, "build_application", scripted_build)
    rte.run_task(TASKS_BY_NAME["inventory_total_value"], "gemma_fullread")
    assert len(sent) == 3
    assert COMPLETED not in sent[2] and "You already ran read_file inventory/service.py" in sent[2]
