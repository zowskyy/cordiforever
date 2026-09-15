from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.event_log import EventLog
from core.events import ASSISTANT_MESSAGE, SYSTEM_MESSAGE, TOOL_RESULT, USER_MESSAGE, Event, Manifest
from core.reality import RequestEnvelope, RealityProjector

SESSION = "s1"
TASK = "t1"
SYSTEM = "You are a careful, deterministic assistant."
SCHEMAS = [{"function": {"name": "write_file", "parameters": {"type": "dict"}}}]
MANIFEST = Manifest(digest="sha-abc123", tool_schema_hash="ts-1", prompt_hash="ph-1", budget_tokens=3000)


def _append(log, etype, payload):
    log.append(Event(type=etype, session_id=SESSION, payload=payload, task_id=TASK))


def _interaction(log):
    _append(log, USER_MESSAGE, {"content": "Create a.txt with content hi"})
    _append(
        log,
        ASSISTANT_MESSAGE,
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": {"path": "a.txt", "content": "hi"},
                    },
                }
            ],
        },
    )
    _append(
        log,
        TOOL_RESULT,
        {
            "tool_name": "write_file",
            "arguments": {"path": "a.txt", "content": "hi"},
            "content": "ok",
            "success": True,
        },
    )
    _append(log, ASSISTANT_MESSAGE, {"content": "wrote a.txt", "tool_calls": None})


def _new_log():
    return EventLog(Path(tempfile.mkdtemp(prefix="env_test_")) / "e.db")


def _payload(env):
    return json.loads(env.serialized_bytes.decode("utf-8"))


def test_compiler_exists_and_is_bound():
    log = _new_log()
    _interaction(log)
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    assert isinstance(env, RequestEnvelope)
    assert env.conversation_head == log.get_last_event(SESSION).id
    assert env.runtime_manifest == MANIFEST.digest
    assert env.serializer_version == MANIFEST.serializer_version
    assert env.compiler_version == "cordiiv2-1.0"


def test_clean_room_replay_identical_hash():
    """Core invariant: same log + manifest + assets → identical bytes/hash."""
    log = _new_log()
    _interaction(log)
    a = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    b = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    assert a.full_request_hash == b.full_request_hash
    assert a.request_prefix_hash == b.request_prefix_hash
    assert a.serialized_bytes == b.serialized_bytes


def test_prefix_hash_independent_of_transcript():
    """Prefix = system prompt + tool schemas only; transcript changes hash only the full body."""
    log = _new_log()
    _interaction(log)
    base = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)

    log2 = _new_log()
    _append(log2, USER_MESSAGE, {"content": "Create a.txt with content hi"})
    _append(log2, ASSISTANT_MESSAGE, {"content": "wrote a.txt", "tool_calls": None})
    _append(log2, USER_MESSAGE, {"content": "a DIFFERENT history"})

    other = RealityProjector(log2).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    assert other.request_prefix_hash == base.request_prefix_hash
    assert other.full_request_hash != base.full_request_hash


def test_different_system_prompt_changes_prefix_hash():
    """Prefix = system prompt + tool schemas. Changing the prompt asset changes both hashes."""
    log = _new_log()
    _interaction(log)
    base = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    other = RealityProjector(log).compile_request(SESSION, MANIFEST, "You are terse.", SCHEMAS)
    assert other.request_prefix_hash != base.request_prefix_hash
    assert other.full_request_hash != base.full_request_hash
    assert other.runtime_manifest == base.runtime_manifest


def test_different_tool_schemas_change_prefix_hash():
    """Changing only the tool schemas isolates the change to the prefix hash (not the body)."""
    log = _new_log()
    _interaction(log)
    base = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    schemas2 = [{"function": {"name": "read_file", "parameters": {"type": "dict"}}}]
    other = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, schemas2)
    assert other.request_prefix_hash != base.request_prefix_hash


def test_log_tamper_advances_head_and_changes_hash():
    log = _new_log()
    _interaction(log)
    first = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    _append(log, USER_MESSAGE, {"content": "tamper"})
    second = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    assert second.conversation_head == first.conversation_head + 1
    assert second.full_request_hash != first.full_request_hash


def test_truncation_is_budget_bounded_but_keeps_system():
    """Projection policy P keeps a bounded newest window; system prompt is always retained."""
    log = _new_log()
    _interaction(log)
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS, budget_tokens=40)
    msgs = _payload(env)
    assert msgs[0]["role"] == "system"
    assert env.estimated_tokens <= 40
    assert len(msgs) < 5  # transcript was truncated from the full 4-event interaction


def test_tool_call_and_result_pair_not_orphaned():
    """At full budget, a tool result must be immediately preceded by an assistant with tool_calls."""
    log = _new_log()
    _interaction(log)
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    msgs = _payload(env)
    tool_idx = next(i for i, m in enumerate(msgs) if m.get("role") == "tool")
    assert msgs[tool_idx - 1]["role"] == "assistant"
    assert bool(msgs[tool_idx - 1].get("tool_calls"))


def test_system_message_folds_into_transcript():
    """Durability parity: a system.message event (e.g. memory) folds into the compiled prompt."""
    log = _new_log()
    _append(log, USER_MESSAGE, {"content": "hi"})
    _append(log, SYSTEM_MESSAGE, {"content": "remember: prefer Python"})
    _append(log, ASSISTANT_MESSAGE, {"content": "ok", "tool_calls": None})
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    msgs = _payload(env)
    assert [m["role"] for m in msgs] == ["system", "user", "system", "assistant"]
    assert msgs[0]["content"] == SYSTEM
    assert msgs[2]["content"] == "remember: prefer Python"


def test_consecutive_duplicate_tool_results_are_not_duplicated_in_prompt():
    """Projection invariant: the compiled prompt carries each tool result once."""
    log = _new_log()
    _append(log, USER_MESSAGE, {"content": "Create a.txt"})
    _append(log, ASSISTANT_MESSAGE, {"content": "", "tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hi"}}}]})
    _append(log, TOOL_RESULT, {"tool_name": "write_file", "result": "ok", "success": True})
    _append(log, TOOL_RESULT, {"tool_name": "write_file", "result": "ok", "success": True})
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    msgs = _payload(env)
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "ok"


def test_tool_result_reads_tool_key():
    """Fold must read both `tool_name` and `tool` payload keys (loop emits both shapes)."""
    log = _new_log()
    _append(log, USER_MESSAGE, {"content": "x"})
    _append(log, ASSISTANT_MESSAGE, {"content": "", "tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hi"}}}]})
    _append(log, TOOL_RESULT, {"tool": "write_file", "result": "done", "success": True})
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    msgs = _payload(env)
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_name"] == "write_file"
    assert tool_msgs[0]["content"] == "done"


def test_envelope_messages_carries_roles_for_model_feed():
    """envelope.messages (list[Message]) is the list the model consumes; roles match the serialized payload."""
    log = _new_log()
    _interaction(log)
    env = RealityProjector(log).compile_request(SESSION, MANIFEST, SYSTEM, SCHEMAS)
    assert isinstance(env.messages, list)
    assert len(env.messages) == len(_payload(env))
    assert [m.role for m in env.messages] == [m["role"] for m in _payload(env)]
