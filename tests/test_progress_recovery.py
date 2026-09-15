"""gemma_progress_v1 mechanism: recovery messages for repeated successful reads and repeated reads of missing paths."""

from __future__ import annotations

import pytest

from core.messages import Message
from core.outcomes import EscalationRequired
from tests.test_agent import _build_agent_with_schema, _tc_compact

ON = {"progress_recovery": True, "repeat_retry_temperature": 0.4}
OFF = {"repeat_retry_temperature": 0.4}


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _run(tmp_path, responses, calibration):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("gamma\n", encoding="utf-8")
    ctx, reg = _build_agent_with_schema(tmp_path, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = 12
    model = ctx.plugins["ollama_model"]
    model.options = {"temperature": 0.0}  # the repeat policy needs sampling options to resample
    sent: list[list[Message]] = []
    original = model.chat
    model.chat = lambda messages, tools: (sent.append(list(messages)), original(messages, tools))[1]
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        result = ctx.plugins["agent_loop"].run("Count the lines in notes.txt and write the count to count.txt")
        error = None
    except EscalationRequired as exc:
        result, error = None, exc
    finally:
        reg.stop_all()
    return result, error, sent, events


def _texts(messages):
    return [(m.role, m.content or "") for m in messages]


def test_repeated_successful_read_is_answered_as_the_calls_tool_result(tmp_path):
    result, _, sent, events = _run(tmp_path, [
        _call("read", path="notes.txt"), _call("read", path="notes.txt"),
        _call("write", path="count.txt", content="2"), _call("done", summary="ok"),
    ], ON)
    assert result == "ok" and (tmp_path / "count.txt").read_text(encoding="utf-8") == "2"
    third = _texts(sent[2])
    expected = ("Not executed: notes.txt was already read by your earlier action and its complete contents (2 lines) are in the tool result above. "
                "The file has not changed since, so reading it again shows nothing new. Your next action must be something other than reading notes.txt.")
    assert third[-1] == ("tool", expected) and third[-2][0] == "assistant"
    assert not any("You already ran" in text for _, text in third)
    assert [p["state"] for t, p in events if t == "progress.recovery"] == ["repeated_successful_read"]
    assert [p["tool"] for t, p in events if t == "tool.result" and p.get("success")] == ["read_file", "write_file"]


def test_repeated_read_thresholds_match_the_control_arm(tmp_path):
    rounds = {}
    for label, calibration in (("on", ON), ("off", OFF)):
        _, error, _, events = _run(tmp_path / label, [_call("read", path="notes.txt") for _ in range(12)], calibration)
        assert error is not None and error.outcome.reason == "repeated_failed_call"
        rounds[label] = (error.outcome.round, sum(1 for t, _ in events if t == "model.resampled"))
    assert rounds["on"] == rounds["off"]


def test_repeated_missing_path_gets_one_recovery_before_the_repeat_policy(tmp_path):
    _, error, sent, events = _run(tmp_path, [_call("read", path="missing.txt") for _ in range(6)], ON)
    recoveries = [p for t, p in events if t == "progress.recovery"]
    assert [(p["state"], p["path"]) for p in recoveries] == [("repeated_missing_path", "missing.txt")]
    expected = ("Not executed: your earlier action already established that missing.txt does not exist, and the workspace has not changed since. "
                "This identical path will not be tried again. Your next action must be something other than reading missing.txt.")
    assert _texts(sent[2])[-1] == ("tool", expected)
    assert error is not None and error.outcome.reason == "repeated_failed_call"
    order = [t for t, _ in events if t in ("progress.recovery", "model.resampled")]
    assert order[0] == "progress.recovery" and "model.resampled" in order

    _, error_off, _, events_off = _run(tmp_path / "off", [_call("read", path="missing.txt") for _ in range(6)], OFF)
    assert not [t for t, _ in events_off if t == "progress.recovery"]
    assert error_off.outcome.round < error.outcome.round  # control resamples on the first repeat; treatment adds one round


def test_recovery_text_never_names_other_workspace_files(tmp_path):
    _, _, sent, _ = _run(tmp_path, [_call("read", path="note.txt") for _ in range(4)], ON)
    recovery = [text for m in sent for role, text in _texts(m) if role == "tool" and text.startswith("Not executed")]
    assert recovery and not any("notes.txt" in t or "other.txt" in t for t in recovery)


def test_missing_path_recovery_resets_when_the_workspace_changes(tmp_path):
    _, _, _, events = _run(tmp_path, [
        _call("read", path="missing.txt"), _call("read", path="missing.txt"),
        _call("write", path="count.txt", content="2"), _call("read", path="missing.txt"), _call("done", summary="x"),
    ], ON)
    # After the write (mutation version changed) the read is a new attempt: executed, fails, no recovery message.
    assert len([p for t, p in events if t == "progress.recovery"]) == 1
    assert [p["success"] for t, p in events if t == "tool.result" and p.get("tool") == "read_file" and "recovery" not in p] == [False, False]


def test_off_by_default_and_writes_to_missing_paths_are_not_covered(tmp_path):
    _, _, sent, events = _run(tmp_path, [_call("read", path="notes.txt"), _call("read", path="notes.txt"), _call("done", summary="x")], OFF)
    assert not [t for t, _ in events if t == "progress.recovery"]
    assert any("You already ran read_file notes.txt" in text for _, text in _texts(sent[2]))

    _, _, _, events = _run(tmp_path / "w", [_call("write", path="sub/missing.txt", content="x") for _ in range(2)] + [_call("done", summary="x")], ON)
    assert not [t for t, _ in events if t == "progress.recovery"]
