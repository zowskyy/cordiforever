from __future__ import annotations

import re
from typing import Any

from .events import Event
from .messages import Message


class Summarizer:
    def __init__(self, model: Any = None) -> None:
        self._model = model

    def summarize_events(self, events: list[Event], max_length: int = 500) -> str:
        if not events:
            return ""
        if self._model is None:
            return self._heuristic_summary(events, max_length)
        text = self._format_events_for_summary(events)
        prompt = (
            "Summarize these agent events concisely, focusing on:\n"
            "- What the user asked\n"
            "- What tools were used\n"
            "- Key results or errors\n"
            "- Current state\n\n"
            f"Events:\n{text}\n\n"
            f"Summary (max {max_length} chars):"
        )
        return self._model.generate(prompt)

    def _heuristic_summary(self, events: list[Event], max_length: int) -> str:
        parts = []
        for event in events[-10:]:
            payload = event.payload or {}
            if event.type == "user.message":
                parts.append(f"User: {payload.get('content', '')[:100]}")
            elif event.type == "tool.result":
                tool = payload.get("tool_name", "unknown")
                if payload.get("success"):
                    parts.append(f"Tool {tool} succeeded")
                else:
                    parts.append(f"Tool {tool} failed: {payload.get('error', '')[:50]}")
        summary = "; ".join(parts)
        return summary[:max_length]

    def _format_events_for_summary(self, events: list[Event]) -> str:
        lines = []
        for event in events[-20:]:
            payload = event.payload or {}
            if event.type == "user.message":
                lines.append(f"[{event.timestamp}] User: {payload.get('content', '')}")
            elif event.type == "assistant.message":
                lines.append(f"[{event.timestamp}] Assistant: {payload.get('content', '')[:200]}")
            elif event.type == "tool.result":
                tool = payload.get("tool_name", "unknown")
                status = "ok" if payload.get("success") else f"error: {payload.get('error', '')[:100]}"
                lines.append(f"[{event.timestamp}] Tool {tool}: {status}")
        return "\n".join(lines)

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def fold_messages(messages: list[Any], max_messages: int = 40, task_state: dict[str, Any] | None = None) -> list[Any]:
        # Single authoritative pruner: delegate to ContextPruner so invariant 2.6
        # (one pruning path, tool_calls preserved) is enforced in one place.
        if len(messages) <= max_messages:
            return messages

        from .context_pruner import ContextPruner
        pruner = ContextPruner(max_messages=max_messages - 1)
        result = pruner.prune(messages, task_state)
        pruned = result.messages

        task_state = task_state or {}
        user_goal = task_state.get("goal", "")
        files_touched = task_state.get("files_touched", [])
        tools_used = task_state.get("tools_used", [])
        unresolved = task_state.get("unresolved_subtasks", [])

        # Parse previous fold context for delta ledger
        prev_files: list[str] = []
        for m in pruned:
            if getattr(m, "role", None) == "system" and "[Context folded]" in (getattr(m, "content", "") or ""):
                mt = re.search(r"Files: ([^|]+)", m.content)
                if mt:
                    prev_files = [f.strip() for f in mt.group(1).split(",") if f.strip()]
                mt2 = re.search(r"\+(\d+): ([^|]+)", m.content)
                if mt2:
                    prev_files.extend([f.strip() for f in mt2.group(2).split(",") if f.strip()])

        if prev_files:
            new_files = [f for f in files_touched if f not in prev_files]
            if new_files:
                ledger_parts = [f"Task: {user_goal}", f"+{len(new_files)}: {', '.join(new_files)}"]
            else:
                ledger_parts = [f"Task: {user_goal}"]
                if tools_used:
                    new_tools = [t for t in tools_used if t not in prev_files]
                    if new_tools:
                        ledger_parts.append(f"Tools +{len(new_tools)}: {', '.join(new_tools)}")
        else:
            ledger_parts = [f"Task: {user_goal}"]
            if files_touched:
                ledger_parts.append(f"Files: {', '.join(files_touched)}")
            if tools_used:
                ledger_parts.append(f"Tools used: {', '.join(tools_used)}")
        if unresolved:
            ledger_parts.append(f"Remaining: {', '.join(unresolved)}")
        ledger = " | ".join(ledger_parts)

        # Injected context as user message per invariant 2.7
        summary_msg = Message(role="user", content=f"[injected context]\n{ledger}")

        result_list = [summary_msg] + pruned
        return result_list[:max_messages]
