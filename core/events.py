from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


# Event type constants
SESSION_START = "session.start"
SESSION_END = "session.end"
USER_MESSAGE = "user.message"
ASSISTANT_MESSAGE = "assistant.message"
SYSTEM_MESSAGE = "system.message"
TOOL_INVOKED = "tool.invoked"
TOOL_RESULT = "tool.result"
TOOL_ERROR = "tool.error"
TOOL_CALL_START = "tool.call.start"
TOOL_CALL_END = "tool.call.end"
TOOL_RESULT_PRUNED = "tool.result.pruned"
TOOL_RESULT_SPILLED = "tool.result.spilled"
TASK_START = "task.start"
TASK_END = "task.end"
GEN_START = "gen.start"
GEN_COMPLETE = "gen.complete"
GEN_SENT = "gen.sent"
STEP_TRACE = "step.trace"
SESSION_LIST = "session.list"
SESSION_DELETED = "session.deleted"
DOMAIN_CHANGED = "domain.changed"
TOOLS_CHANGED = "tools.change"


EventType = Literal[
    "session.start",
    "session.end",
    "user.message",
    "assistant.message",
    "system.message",
    "tool.invoked",
    "tool.result",
    "tool.error",
    "tool.call.start",
    "tool.call.end",
    "tool.result.pruned",
    "tool.result.spilled",
    "model.requested",
    "model.responded",
    "manifest_bound",
    "compaction_checkpoint",
    "context_pruned",
    "approval_granted",
    "task.start",
    "task.end",
    "step.trace",
    "session.list",
    "session.deleted",
    "domain.changed",
    "tools.change",
]


@dataclass
class Manifest:
    """Resolved runtime binding for a projection epoch.

    The manifest pins the assets the compiler C consumes (tool schemas, prompt
    template, serializer version, capacity budget) to immutable identities so a
    request is reproducible from (log, manifest, policy) alone.
    """
    digest: str
    tool_schema_hash: str
    prompt_hash: str
    serializer_version: str = "v1"
    profile: str = "lite"
    budget_tokens: int = 3000


@dataclass
class Event:
    type: str
    session_id: str
    payload: dict[str, Any]
    id: int | None = None
    timestamp: str = field(default_factory=lambda: _utc_now())
    task_id: str | None = None
    parent_event_id: int | None = None
    operation_id: str | None = None
    prev_hash: str | None = None
    entry_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "type": self.type,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "parent_event_id": self.parent_event_id,
            "operation_id": self.operation_id,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }

    @classmethod
    def from_row(cls, row: tuple) -> Event:
        return cls(
            id=row[0],
            timestamp=row[1],
            type=row[2],
            session_id=row[3],
            task_id=row[4],
            parent_event_id=row[5],
            operation_id=row[6],
            payload=json.loads(row[7]) if row[7] else {},
            prev_hash=row[8] if len(row) > 8 else None,
            entry_hash=row[9] if len(row) > 9 else None,
        )


@dataclass
class TraceStep:
    step_id: str
    session_id: str
    tool_name: str
    input: dict[str, Any]
    output: str = ""
    duration_ms: float = 0.0
    error_type: str | None = None
    token_cost: int = 0
    context_size_before: int = 0
    context_size_after: int = 0
    dependency_ids: list[str] = field(default_factory=list)
    parallelizable: bool = False
    governance_check_passed: bool = True
    timestamp: str = field(default_factory=lambda: _utc_now())


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
