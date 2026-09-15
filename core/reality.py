from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from core.messages import Message
from .events import Manifest, Event, USER_MESSAGE, ASSISTANT_MESSAGE, SYSTEM_MESSAGE, TOOL_RESULT, TOOL_ERROR, TASK_START


@dataclass
class CurrentReality:
    messages: list[dict[str, Any]] = field(default_factory=list)
    files_read: set[str] = field(default_factory=set)
    files_written: set[str] = field(default_factory=set)
    files_listed: set[str] = field(default_factory=set)
    tools_used: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    task_ids: set[str] = field(default_factory=set)
    last_event_id: int = 0
    last_timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "files_read": list(self.files_read), "files_written": list(self.files_written), "files_listed": list(self.files_listed), "task_ids": list(self.task_ids)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurrentReality:
        return cls(
            messages=data.get("messages", []),
            files_read=set(data.get("files_read", [])),
            files_written=set(data.get("files_written", [])),
            files_listed=set(data.get("files_listed", [])),
            tools_used=data.get("tools_used", []),
            errors=data.get("errors", []),
            task_ids=set(data.get("task_ids", [])),
            last_event_id=data.get("last_event_id", 0),
            last_timestamp=data.get("last_timestamp"),
        )

    def apply_event(self, event: Event) -> None:
        if event.id is not None:
            self.last_event_id = max(self.last_event_id, event.id)
        self.last_timestamp = event.timestamp
        if event.task_id:
            self.task_ids.add(event.task_id)
        payload = event.payload or {}
        if event.type == USER_MESSAGE:
            self.messages.append({"role": "user", "content": payload.get("content", "")})
        elif event.type == SYSTEM_MESSAGE:
            self.messages.append({"role": "system", "content": payload.get("content", "")})
        elif event.type == ASSISTANT_MESSAGE:
            self.messages.append({"role": "assistant", "content": payload.get("content", ""), "tool_calls": payload.get("tool_calls")})
        elif event.type == TOOL_RESULT:
            tool_name = payload.get("tool_name") or payload.get("tool", "")
            self.tools_used.append(tool_name)
            content = payload.get("content") or payload.get("result", payload.get("error", ""))
            self.messages.append({"role": "tool", "content": content, "tool_name": tool_name})
            path = payload.get("arguments", {}).get("path", "")
            if tool_name == "file_read" and path:
                self.files_read.add(path)
            elif tool_name == "file_write" and path:
                self.files_written.add(path)
            elif tool_name == "file_list":
                self.files_listed.add(path or ".")
            if payload.get("success") is False:
                self.errors.append({"tool": tool_name, "error": payload.get("error", "Unknown error"), "timestamp": event.timestamp})
        elif event.type == TOOL_ERROR:
            self.errors.append({"tool": payload.get("tool_name", "unknown"), "error": payload.get("error", "Unknown error"), "timestamp": event.timestamp})
        elif event.type == TASK_START and event.task_id:
            self.task_ids.add(event.task_id)

    def summary(self) -> dict[str, Any]:
        return {"message_count": len(self.messages), "files_read": sorted(self.files_read), "files_written": sorted(self.files_written), "files_listed": sorted(self.files_listed), "tools_used": self.tools_used, "error_count": len(self.errors), "tasks": sorted(self.task_ids), "last_activity": self.last_timestamp}


@dataclass
class RequestEnvelope:
    """Compiler C output: deterministic, hashed request bytes for one turn.

    serialized_bytes = C(Lc, Lr, M, S, P, A): fold the event log through the
    projection policy (P), serialize under the manifest serializer (S), and bind
    to the resolved manifest (M). full_request_hash makes clean-room replay
    checkable; request_prefix_hash isolates the stable prefix (system prompt +
    tool schemas) from the turn-varying transcript.
    """
    conversation_head: int
    runtime_manifest: str
    compiler_version: str
    projection_policy: str
    serializer_version: str
    request_prefix_hash: str
    full_request_hash: str
    serialized_bytes: bytes
    estimated_tokens: int
    messages: list[Message] = field(default_factory=list)


def _truncate_to_budget(messages: list[dict[str, Any]], budget_tokens: int, system_prompt: str, tool_schemas: list) -> list[dict[str, Any]]:
    """Projection policy P: newest-first fold onto budget_tokens, preserving tool_call/tool-result pairs."""
    from core.summarizer import Summarizer

    def est(text: str) -> int:
        return Summarizer.estimate_tokens(text)

    prefix = system_prompt + json.dumps(list(tool_schemas), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    remaining = max(0, budget_tokens - est(prefix))
    kept: list[dict[str, Any]] = []
    used = 0
    for m in reversed(messages):
        cost = est(json.dumps(m, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        if used + cost <= remaining:
            kept.append(m)
            used += cost
        else:
            break
    kept.reverse()
    repaired: list[dict[str, Any]] = []
    for m in kept:
        if m.get("role") == "tool":
            if repaired and repaired[-1].get("role") == "assistant" and bool(repaired[-1].get("tool_calls")):
                repaired.append(m)
        else:
            repaired.append(m)
    return repaired


class RealityProjector:
    def __init__(self, event_log: Any, snapshot_threshold: int = 50) -> None:
        self._event_log = event_log
        self._snapshot_threshold = snapshot_threshold
        self._cache: dict[str, CurrentReality] = {}

    def get_reality(self, session_id: str) -> CurrentReality:
        if session_id in self._cache:
            return self._cache[session_id]
        snapshot = self._event_log.load_snapshot(session_id)
        if snapshot:
            version, state_dict = snapshot
            reality = CurrentReality.from_dict(state_dict)
            events = self._event_log.get_events_after(session_id, version)
        else:
            reality = CurrentReality()
            events = self._event_log.get_session_events(session_id)
        for event in events:
            reality.apply_event(event)
        if len(events) >= self._snapshot_threshold:
            self._event_log.save_snapshot(session_id, reality.last_event_id, reality.to_dict())
        self._cache[session_id] = reality
        return reality

    def invalidate_cache(self, session_id: str | None = None) -> None:
        if session_id:
            self._cache.pop(session_id, None)
        else:
            self._cache.clear()

    def compile_request(
        self,
        session_id: str,
        manifest: Manifest,
        system_prompt: str,
        tool_schemas: list,
        budget_tokens: int | None = None,
    ) -> RequestEnvelope:
        """C(Lc, Lr, M, S, P, A): fold log through P, serialize under S, bind to M.

        Pure w.r.t. (log revision, manifest, assets): two clean-room projectors
        over the same log + manifest produce identical envelopes (full_request_hash).
        """
        from core.summarizer import Summarizer

        reality = self.get_reality(session_id)
        budget = budget_tokens or manifest.budget_tokens
        kept = _truncate_to_budget(reality.messages, budget, system_prompt, tool_schemas)
        prefix_json = json.dumps(
            {"system_prompt": system_prompt, "tool_schemas": list(tool_schemas)},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        payload = [{"role": "system", "content": system_prompt}, *kept]
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        messages = [Message.from_dict(d) for d in payload]
        return RequestEnvelope(
            conversation_head=reality.last_event_id,
            runtime_manifest=manifest.digest,
            compiler_version="cordiiv2-1.0",
            projection_policy="truncate:newest-first;preserve tool pairs",
            serializer_version=manifest.serializer_version,
            request_prefix_hash=hashlib.sha256(prefix_json.encode("utf-8")).hexdigest(),
            full_request_hash=hashlib.sha256(serialized).hexdigest(),
            serialized_bytes=serialized,
            estimated_tokens=Summarizer.estimate_tokens(serialized.decode("utf-8", "replace")),
            messages=messages,
        )
