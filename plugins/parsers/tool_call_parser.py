from __future__ import annotations

from typing import Any, List

from core.messages import Message
from core.plugin import EventDrivenPlugin
from core.tool_call_extraction import extract_tool_calls_from_text


class ToolCallParser(EventDrivenPlugin):
    name = "tool_call_parser"

    def parse(self, message: Message, tools: List[dict[str, Any]]) -> List[dict[str, Any]]:
        raise NotImplementedError


class OllamaToolCallParser(ToolCallParser):
    name = "ollama_tool_call_parser"

    def parse(self, message: Message, tools: List[dict[str, Any]]) -> List[dict[str, Any]]:
        return extract_tool_calls_from_text(message.content or "", tools)
