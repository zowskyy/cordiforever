from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    role: str
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.name is not None:
            result["name"] = self.name
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.tool_calls is not None:
            result["tool_calls"] = self.tool_calls
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=str(data["role"]),
            content=str(data.get("content", "")),
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
            tool_name=data.get("tool_name"),
            tool_calls=data.get("tool_calls"),
        )
