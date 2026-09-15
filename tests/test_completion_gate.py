from __future__ import annotations

import pytest

from core.messages import Message
from core.outcomes import EscalationRequired
from tests.test_agent import build_agent, tc

GATE = {"calibration": {"require_read_named_files": True}}


def _agent(tmp_path, responses, config=GATE):
    ctx, reg = build_agent(tmp_path, responses, config=config)
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    return ctx, reg, events


def _seed(tmp_path, *paths):
    for rel in paths:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")


def test_done_before_reading_named_file_is_refused_then_allowed_after_read(tmp_path):
    _seed(tmp_path, "docs/notes.txt")
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "count.txt", "content": "10"})]),
        Message("assistant", "Task completed successfully."),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "docs/notes.txt"})]),
        Message("assistant", "Counted 3 lines."),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("Read notes.txt, then write count.txt with the line count.") == "Counted 3 lines."
        assert [p["unread"] for t, p in events if t == "done.rejected"] == [[["docs/notes.txt"]]]
        checks = [m.content for m in ctx.messages if m.role == "user" and m.content.startswith("[completion check]")]
        assert checks == ["[completion check] The task names files you have not read yet: docs/notes.txt. Read them before finishing."]
    finally:
        reg.stop_all()


def test_second_unmet_finish_escalates(tmp_path):
    _seed(tmp_path, "notes.txt")
    ctx, reg, events = _agent(tmp_path, [Message("assistant", "done"), Message("assistant", "really done")])
    try:
        with pytest.raises(EscalationRequired) as raised:
            ctx.plugins["agent_loop"].run("Summarize notes.txt")
        assert raised.value.outcome.reason == "completion_prerequisites_unmet"
        assert raised.value.outcome.repeated_calls == ["notes.txt"]
    finally:
        reg.stop_all()


def test_deleted_named_file_satisfies_requirement(tmp_path):
    _seed(tmp_path, "temp.txt")
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("delete_file", {"path": "temp.txt"})]),
        Message("assistant", "Removed temp.txt."),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("Remove temp.txt") == "Removed temp.txt."
        assert not [t for t, _ in events if t == "done.rejected"]
    finally:
        reg.stop_all()


def test_ambiguous_name_satisfied_by_reading_any_candidate(tmp_path):
    _seed(tmp_path, "config/app.json", "deploy/app.json")
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "deploy/app.json"})]),
        Message("assistant", "Checked."),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("Check app.json") == "Checked."
        assert not [t for t, _ in events if t == "done.rejected"]
    finally:
        reg.stop_all()


def test_new_file_names_create_no_requirement(tmp_path):
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "hello.py", "content": "print('hi')"})]),
        Message("assistant", "Created."),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("Create hello.py that prints hi") == "Created."
    finally:
        reg.stop_all()


GATE_WITH_OVERWRITE_GUARD = {"calibration": {"require_read_named_files": True, "require_read_before_write": True}}


def _rejections(events):
    return [p["reason"] for t, p in events if t == "guard.rejected"]


def test_wipe_replay_mutation_needs_real_read_of_named_file(tmp_path):
    # Observed: config.json overwritten with "8080"; guard-shown contents let the identical write through next round.
    (tmp_path / "config.json").write_text('{"name": "demo", "port": 3000}', encoding="utf-8")
    wipe = tc("write_file", {"path": "config.json", "content": "8080"})
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[wipe]),
        Message("assistant", "", tool_calls=[wipe]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "config.json"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "config.json", "content": '{"name": "demo", "port": 8080}'})]),
        Message("assistant", "done"),
    ], config=GATE_WITH_OVERWRITE_GUARD)
    try:
        assert ctx.plugins["agent_loop"].run("config.json sets port to 3000. Change the port to 8080.") == "done"
        assert _rejections(events) == ["named_file_unread", "named_file_unread"]
        assert (tmp_path / "config.json").read_text(encoding="utf-8") == '{"name": "demo", "port": 8080}'
    finally:
        reg.stop_all()


def test_ambiguous_name_requires_reading_the_exact_mutation_target(tmp_path):
    _seed(tmp_path, "src/config.json", "config/config.json")
    target = tc("write_file", {"path": "config/config.json", "content": "updated"})
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "src/config.json"})]),
        Message("assistant", "", tool_calls=[target]),
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "config/config.json"})]),
        Message("assistant", "", tool_calls=[target]),
        Message("assistant", "done"),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("Update config.json") == "done"
        assert _rejections(events) == ["named_file_unread"]
        assert (tmp_path / "config" / "config.json").read_text(encoding="utf-8") == "updated"
        assert (tmp_path / "src" / "config.json").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"
    finally:
        reg.stop_all()


def test_delete_of_named_file_needs_no_read(tmp_path):
    _seed(tmp_path, "old.log")
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("delete_file", {"path": "old.log"})]),
        Message("assistant", "Deleted."),
    ])
    try:
        assert ctx.plugins["agent_loop"].run("The file old.log is obsolete; it should no longer exist.") == "Deleted."
        assert ctx.plugins["ollama_model"].calls == 2
        assert not (tmp_path / "old.log").exists()
        assert _rejections(events) == []
    finally:
        reg.stop_all()


def test_unnamed_existing_file_is_not_subject_to_named_rule(tmp_path):
    _seed(tmp_path, "notes.txt", "other.txt")
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("read_file", {"path": "notes.txt"})]),
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "other.txt", "content": "x"})]),
        Message("assistant", "done"),
    ])
    try:
        ctx.plugins["agent_loop"].run("Summarize notes.txt")
        assert "named_file_unread" not in _rejections(events)
        assert (tmp_path / "other.txt").read_text(encoding="utf-8") == "x"
    finally:
        reg.stop_all()


def test_named_mutation_rule_off_without_calibration(tmp_path):
    _seed(tmp_path, "notes.txt")
    ctx, reg, events = _agent(tmp_path, [
        Message("assistant", "", tool_calls=[tc("write_file", {"path": "notes.txt", "content": "x"})]),
        Message("assistant", "done"),
    ], config=None)
    try:
        ctx.plugins["agent_loop"].run("Rewrite notes.txt")
        assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "x"
    finally:
        reg.stop_all()


def test_gate_off_by_default(tmp_path):
    _seed(tmp_path, "notes.txt")
    ctx, reg, events = _agent(tmp_path, [Message("assistant", "done")], config=None)
    try:
        assert ctx.plugins["agent_loop"].run("Summarize notes.txt") == "done"
        assert not [t for t, _ in events if t == "done.rejected"]
    finally:
        reg.stop_all()
