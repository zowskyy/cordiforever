"""Producer-contract tests for `D3_CALL_POSITION_CONTRACT` (benchmark/analysis/furthest_bottleneck_taxonomy_v2.md §3a).

The D3-v2 methodology depends on how `benchmark/repo_task_eval.call_log` constructs persisted call rounds. These
tests pin that construction behaviourally — a whole-file hash would break on unrelated edits and train people to
re-bless it — so a future change to the round semantics fails here rather than silently invalidating the methodology.

Pinned properties:
  1. the positional counter starts at 0, so a call before the first `turn.round` is persisted at round 0;
  2. `turn.round` is the advancement event, +1 per observed event;
  3. calls between two `turn.round` events share the current positional round;
  4. payload `round` values never override the positional counter;
  5. unrelated events do not advance the counter;
  6. persisted rounds are plain ints and non-decreasing in recorded order, for any timeline.

Synthetic timelines and a scripted model only: no inference, no network, no real result row is read.
"""

from __future__ import annotations

import random
import shutil

import pytest

from benchmark.repo_task_eval import call_log

SEED_TEXTS = {"a.py": "x = 1\n"}


def result(tool="diagnose", path="a.py", payload_round=None, success=True):
    payload = {"tool": tool, "arguments": {"path": path}, "result": "ok", "success": success}
    if payload_round is not None:
        payload["round"] = payload_round
    return ("tool.result", payload)


def turn(round_hint=0):
    return ("turn.round", {"round": round_hint})


def rounds_for(timeline):
    calls, _views = call_log(timeline, SEED_TEXTS)
    return [c["round"] for c in calls]


# ============================================================================= exact positional construction
def test_call_before_first_turn_round_is_persisted_at_zero():
    assert rounds_for([result()]) == [0]


def test_turn_round_advances_the_counter_by_one():
    assert rounds_for([turn(), result()]) == [1]
    assert rounds_for([turn(), turn(), result()]) == [2]
    assert rounds_for([turn(), turn(), turn(), result()]) == [3]


def test_calls_without_an_intervening_turn_round_share_a_round():
    assert rounds_for([turn(), result(), result(), result()]) == [1, 1, 1]


def test_exact_sequence_across_rounds_and_foreign_events():
    """tool.result / turn.round / tool.result x2 / foreign / turn.round / tool.result."""
    timeline = [
        result(),                                   # before any turn.round -> 0
        turn(),
        result(), result(),                         # -> 1, 1
        ("guard.rejected", {"tool": "diagnose", "path": "a.py", "round": 99}),
        ("model.resampled", {}),
        turn(),
        result(),                                   # -> 2
    ]
    assert rounds_for(timeline) == [0, 1, 1, 2]


def test_foreign_events_do_not_advance_the_counter():
    noise = [("guard.rejected", {"round": 41}), ("model.resampled", {}), ("system.message", {"content": "x"}),
             ("repeat.detected", {"calls": []}), ("completion.latch", {})]
    assert rounds_for([turn(), *noise, result()]) == [1]


@pytest.mark.parametrize("payload_round", [9, 0, -5, 999, "seven", None, True])
def test_payload_round_never_overrides_the_positional_counter(payload_round):
    timeline = [turn(), result(payload_round=payload_round), turn(), result(payload_round=payload_round)]
    assert rounds_for(timeline) == [1, 2]


def test_payload_rounds_decreasing_still_persist_increasing():
    assert rounds_for([turn(), result(payload_round=9), turn(), result(payload_round=2)]) == [1, 2]


# ============================================================================= persisted-representation invariant
@pytest.mark.parametrize("name,timeline", [
    ("empty", []),
    ("only_turn_rounds", [turn(), turn()]),
    ("results_only", [result(), result()]),
    ("dense", [turn(), result(), result(), turn(), result(), turn(), turn(), result()]),
])
def test_persisted_rounds_are_plain_ints_and_non_decreasing(name, timeline):
    calls, _views = call_log(timeline, SEED_TEXTS)
    assert all("round" in c for c in calls), name          # the key is always present
    values = [c["round"] for c in calls]
    assert all(type(v) is int for v in values), name       # plain int, never bool or str
    assert values == sorted(values), name


def test_shuffled_timeline_still_yields_non_decreasing_rounds():
    random.seed(1234)
    for _ in range(50):
        timeline = [turn() for _ in range(4)] + [result() for _ in range(6)]
        random.shuffle(timeline)
        values = rounds_for(timeline)
        assert values == sorted(values)
        assert all(type(v) is int for v in values)


# ============================================================================= end-to-end through the real agent loop
INVENTORY_SERVICE = "inventory/service.py"
MISSING = "inventory/nope.py"
FIX = "def total_value(items):\n    return sum(i.price * i.qty for i in items)"


def _scripted(tool, **args):
    from core.messages import Message
    from tests.test_agent import _tc_compact

    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _multi(*pairs):
    from core.messages import Message
    from tests.test_agent import _tc_compact

    return Message("assistant", "", tool_calls=[_tc_compact(t, a) for t, a in pairs])


SHAPES = {
    "multi_call_single_turn": ({}, lambda: [_multi(("read", {"path": INVENTORY_SERVICE}), ("list", {"path": "inventory"})),
                                            _scripted("done", summary="x")]),
    "failed_call": ({}, lambda: [_scripted("read", path=MISSING), _scripted("done", summary="x")]),
    "guard_diagnosis_required": ({"diagnose_before_mutation": True},
                                 lambda: [_scripted("read", path=INVENTORY_SERVICE),
                                          _scripted("edit", path=INVENTORY_SERVICE, selector_kind="python_symbol",
                                                    target="total_value", replacement=FIX),
                                          _scripted("done", summary="x")]),
    "guard_read_before_evidence": ({"read_before_evidence": True, "diagnose_before_mutation": True},
                                   lambda: [_scripted("diagnose", path=INVENTORY_SERVICE, target="total_value",
                                                      evidence="return sum(i.price for i in items)", cause="c", change="m"),
                                            _scripted("read", path=INVENTORY_SERVICE),
                                            _scripted("diagnose", path=INVENTORY_SERVICE, target="total_value",
                                                      evidence="return sum(i.price for i in items)", cause="c", change="m"),
                                            _scripted("done", summary="x")]),
    "repeat_block": ({}, lambda: [_scripted("read", path=MISSING)] * 4 + [_scripted("done", summary="x")]),
    "duplicate_success": ({}, lambda: [_scripted("read", path=INVENTORY_SERVICE), _scripted("read", path=INVENTORY_SERVICE),
                                       _scripted("done", summary="x")]),
    "progress_recovery_repeated_read": ({"progress_recovery": True},
                                        lambda: [_scripted("read", path=INVENTORY_SERVICE)] * 3 + [_scripted("done", summary="x")]),
}


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_real_loop_shapes_persist_non_decreasing_rounds(name, tmp_path):
    """The real AgentLoop, the real event capture and the real call_log, driven by a scripted model."""
    from benchmark.repo_task_eval import REPOS_DIR
    from tests.test_agent import _build_agent_with_schema

    calibration, responses = SHAPES[name]
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS_DIR / "inventory", workspace, ignore=shutil.ignore_patterns("__pycache__"))
    seed_texts = {p.relative_to(workspace).as_posix(): p.read_text(encoding="utf-8")
                  for p in workspace.rglob("*") if p.is_file() and p.suffix in (".py", ".json", ".txt", ".md")}
    ctx, reg = _build_agent_with_schema(workspace, responses(), profile="lite", compact_schema=True,
                                        config={"calibration": calibration})
    timeline: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: timeline.append((e.type, dict(e.payload or {}))))
    ctx.plugins["agent_loop"].max_rounds = 12
    try:
        ctx.plugins["agent_loop"].run("total_value ignores quantities. Fix it.")
    finally:
        reg.stop_all()

    calls, _views = call_log(timeline, seed_texts)
    assert calls, name  # the shape must actually produce calls, or it proves nothing
    assert all("round" in c for c in calls), name
    values = [c["round"] for c in calls]
    assert all(type(v) is int for v in values), name
    assert values == sorted(values), f"{name}: {values}"
