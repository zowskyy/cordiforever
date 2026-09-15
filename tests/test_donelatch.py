"""qwen_donelatch_v1 mechanism: completion is unavailable after an unapplied mutation until a later mutation is applied."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core.messages import Message
from core.outcomes import EscalationRequired
from tests.test_agent import _build_agent_with_schema, _tc_compact

REPOS = Path(__file__).resolve().parents[1] / "benchmark" / "repos"
BASE = {"diagnose_before_mutation": True, "full_read_views": True, "read_before_evidence": True, "evidence_extraction": True,
        "require_read_before_write": True, "localized_edits": True, "explicit_selector_kind": True, "ast_noop_refusal": True}
LATCH = {**BASE, "completion_requires_mutation_success": True}
MESSAGE = "[completion check] Under this condition, completion is unavailable: the most recent attempted change was not applied."
PROMPT = "slugify must remove punctuation."

RESTATED = "def slugify(text):\n    return text.strip().lower().replace(' ', '-')"
RESTATED_2 = "def slugify( text ):\n    return text.strip().lower().replace( ' ', '-' )"
FIX = "def slugify(text):\n    kept = ''.join(ch for ch in text if ch.isalnum() or ch in ' -')\n    return kept.strip().lower().replace(' ', '-')"
FIX_2 = "def slugify(text):\n    kept = ''.join(ch for ch in text if ch.isalnum() or ch in ' -_')\n    return kept.strip().lower().replace(' ', '-')"


def call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def edit(replacement, path="textkit/slugify.py", target="slugify", kind="python_symbol"):
    return call("edit", path=path, selector_kind=kind, target=target, replacement=replacement)


def done(summary="fixed"):
    return call("done", summary=summary)


PREFIX = [call("read", path="textkit/slugify.py"),
          call("diagnose", path="textkit/slugify.py", target="slugify", cause="keeps punctuation", change="remove it")]


def agent(tmp_path, responses, calibration=LATCH, repo="textkit", rounds=14):
    workspace = tmp_path / "ws"
    if not workspace.exists():
        shutil.copytree(REPOS / repo, workspace, ignore=shutil.ignore_patterns("__pycache__"))
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = rounds
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, dict(e.payload))))
    return ctx, reg, events, workspace


def latch(events):
    return [p for t, p in events if t == "completion.latch"]


def actions(events):
    return [p["action"] for p in latch(events)]


def run(tmp_path, responses, calibration=LATCH, prompt=PROMPT, **kw):
    ctx, reg, events, workspace = agent(tmp_path, responses, calibration, **kw)
    try:
        result = ctx.plugins["agent_loop"].run(prompt)
    finally:
        reg.stop_all()
    return result, ctx, events, workspace


def run_escalating(tmp_path, responses, calibration=LATCH, prompt=PROMPT):
    ctx, reg, events, workspace = agent(tmp_path, responses, calibration)
    try:
        with pytest.raises(EscalationRequired) as raised:
            ctx.plugins["agent_loop"].run(prompt)
    finally:
        reg.stop_all()
    return raised.value.outcome, ctx, events


def test_refused_edit_blocks_done_until_a_substantive_edit_is_applied(tmp_path):
    result, ctx, events, workspace = run(tmp_path, PREFIX + [edit(RESTATED), done("premature"), edit(FIX), done("applied")])
    assert result == "applied"
    assert actions(events) == ["set", "blocked", "released"]
    assert [p["reason"] for t, p in events if t == "done.rejected"] == ["mutation_not_applied"]
    assert [m.content for m in ctx.messages if m.role == "user" and m.content.startswith("[completion check]")] == [MESSAGE]
    assert "isalnum" in (workspace / "textkit" / "slugify.py").read_text(encoding="utf-8")


def test_second_blocked_completion_escalates(tmp_path):
    outcome, _, events = run_escalating(tmp_path, PREFIX + [edit(RESTATED), done("one"), done("two")])
    assert outcome.reason == "completion_after_failed_mutation"
    assert actions(events) == ["set", "blocked", "escalated"]


def test_further_failures_while_latched_stay_in_the_same_episode(tmp_path):
    outcome, _, events = run_escalating(tmp_path, PREFIX + [edit(RESTATED), done("one"), edit(RESTATED_2), done("two")])
    assert outcome.reason == "completion_after_failed_mutation"
    records = latch(events)
    assert [r["action"] for r in records] == ["set", "blocked", "escalated"]  # no second "set"
    assert len({r["latch_version"] for r in records}) == 1


def test_release_starts_a_fresh_episode_for_a_later_failure(tmp_path):
    result, _, events, _ = run(tmp_path, PREFIX + [edit(RESTATED), done("one"), edit(FIX), edit(FIX), done("two"), edit(FIX_2), done("three")])
    records = latch(events)
    assert [r["action"] for r in records] == ["set", "blocked", "released", "set", "blocked", "released"]
    first_release, second_set = records[2], records[3]
    assert second_set["latch_version"] >= first_release["mutation_version"]
    assert result == "three"  # counter was reset by the release: the second episode's first block did not escalate


def test_guard_refused_write_sets_the_latch(tmp_path):
    outcome, _, events = run_escalating(tmp_path, PREFIX + [call("write", path="textkit/slugify.py", content=FIX), done("a"), done("b")])
    assert any(t == "guard.rejected" and p["reason"] == "overwrite_existing_file" for t, p in events)
    assert actions(events) == ["set", "blocked", "escalated"]


def test_failed_json_pointer_edit_sets_the_latch(tmp_path):
    responses = [call("read", path="config/app.json"),
                 call("diagnose", path="config/app.json", target="/port", cause="c", change="x"),
                 edit("3000", path="config/app.json", target="/missing_key", kind="json_pointer"), done("a"), done("b")]
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / "configsvc", workspace, ignore=shutil.ignore_patterns("__pycache__"))
    outcome, _, events = run_escalating(tmp_path, responses, prompt="x")
    assert outcome.reason == "completion_after_failed_mutation"
    assert actions(events)[0] == "set"


def test_no_change_replacement_does_not_release(tmp_path):
    current = (REPOS / "textkit" / "textkit" / "slugify.py").read_text(encoding="utf-8").strip("\n")
    outcome, _, events = run_escalating(tmp_path, PREFIX + [edit(RESTATED), done("a"), edit(current), done("b")])
    assert "released" not in actions(events)
    assert outcome.reason == "completion_after_failed_mutation"


def test_latch_persists_across_rounds_with_non_mutating_calls(tmp_path):
    outcome, _, events = run_escalating(tmp_path, PREFIX + [edit(RESTATED), call("read", path="textkit/formatting.py"),
                                                           call("list", path="textkit"), done("a"), done("b")])
    assert actions(events) == ["set", "blocked", "escalated"]


def test_latch_resets_at_a_new_task(tmp_path):
    ctx, reg, events, _ = agent(tmp_path, PREFIX + [edit(RESTATED), done("a"), done("b"), done("second task")])
    loop = ctx.plugins["agent_loop"]
    try:
        with pytest.raises(EscalationRequired):
            loop.run(PROMPT)
        assert loop._latched is True
        assert loop.run("say something") == "second task"
    finally:
        reg.stop_all()
    assert actions(events) == ["set", "blocked", "escalated"]  # the second task produced no latch event


def test_latch_counter_is_separate_from_the_named_file_gate(tmp_path):
    calibration = {**LATCH, "require_read_named_files": True}
    prompt = "In textkit/slugify.py, slugify must remove punctuation."
    responses = [done("before reading")] + PREFIX + [edit(RESTATED), done("latched"), edit(FIX), done("applied")]
    result, _, events, _ = run(tmp_path, responses, calibration, prompt=prompt)
    assert result == "applied"
    rejected = [p for t, p in events if t == "done.rejected"]
    assert len(rejected) == 2 and rejected[1]["reason"] == "mutation_not_applied" and "reason" not in rejected[0]
    assert "escalated" not in actions(events)


def test_re_proposed_successful_edit_is_a_refused_attempt(tmp_path):
    outcome, _, events = run_escalating(tmp_path, PREFIX + [edit(FIX), edit(FIX), done("a"), done("b")])
    assert actions(events) == ["set", "blocked", "escalated"]


def test_successful_edit_then_done_is_never_blocked(tmp_path):
    result, _, events, _ = run(tmp_path, PREFIX + [edit(FIX), done("applied")])
    assert result == "applied" and latch(events) == []
    assert not any(t == "done.rejected" for t, _ in events)


def test_flag_off_leaves_behavior_unchanged(tmp_path):
    result, _, events, _ = run(tmp_path, PREFIX + [edit(RESTATED), done("premature")], calibration=BASE)
    assert result == "premature" and latch(events) == []
    assert not any(t == "done.rejected" for t, _ in events)


def test_message_is_neutral():
    for word in ("slugify", ".py", "line", "should", "instead", "retry", "edit", "fix"):
        assert word not in MESSAGE.lower()


def test_event_payloads_are_complete_and_consistent(tmp_path):
    _, _, events, _ = run(tmp_path, PREFIX + [edit(RESTATED), done("one"), edit(FIX), done("applied")])
    for record in latch(events):
        assert set(record) == {"round", "reason", "latch_version", "mutation_version", "action"}
        if record["action"] in ("blocked", "escalated", "set"):
            assert record["mutation_version"] == record["latch_version"]
        if record["action"] == "released":
            assert record["mutation_version"] > record["latch_version"]
