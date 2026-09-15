from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedToolCall:
    name: str
    arguments: dict[str, Any]
    raw: str = ""
    parse_mode: str = "json"


class ParseError(Exception):
    pass


class JSONToolParser:
    def parse(self, text: str) -> ParsedToolCall:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?", "", text).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"Invalid JSON: {exc}") from exc

        if isinstance(data, dict) and "name" in data:
            return ParsedToolCall(
                name=data["name"],
                arguments=data.get("arguments", {}),
                raw=text,
                parse_mode="json",
            )
        if isinstance(data, list) and data and isinstance(data[0], dict):
            first = data[0]
            return ParsedToolCall(
                name=first.get("name", ""),
                arguments=first.get("arguments", {}),
                raw=text,
                parse_mode="json",
            )
        raise ParseError("JSON does not contain tool call structure")


class TextToolParser:
    PATTERNS: dict[str, list[str]] = {
        "read_file": [r"read\s+(?:the\s+)?(?:file\s+)?(\S+)", r"show\s+(?:me\s+)?(?:the\s+)?(?:contents?\s+of\s+)?(\S+)"],
        "write_file": [r"write\s+(?:to\s+)?(\S+)", r"save\s+(?:to\s+)?(\S+)"],
        "list_directory": [r"list\s+(?:files?\s+)?(?:in\s+)?(\S+)?", r"what\s+files\s+are\s+in\s+(\S+)"],
    }

    def parse(self, text: str) -> ParsedToolCall:
        for tool_name, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    args = {}
                    if match.lastindex and match.group(1):
                        args["path"] = match.group(1)
                    return ParsedToolCall(
                        name=tool_name,
                        arguments=args,
                        raw=text,
                        parse_mode="text",
                    )
        raise ParseError("No tool intent recognized in text")


class ToolProtocol:
    def __init__(self, tools: list[Any] | None = None) -> None:
        self._json_parser = JSONToolParser()
        self._text_parser = TextToolParser()
        self._tools: dict[str, Any] = {}
        if tools:
            for tool in tools:
                schemas = getattr(tool, "schemas", lambda: [])()
                if schemas:
                    for schema in schemas:
                        func_name = schema.get("function", {}).get("name")
                        if func_name:
                            self._tools[func_name] = tool
                else:
                    self._tools[tool.name] = tool

    def parse(self, text: str) -> ParsedToolCall:
        try:
            return self._json_parser.parse(text)
        except ParseError:
            return self._text_parser.parse(text)

    def validate(self, parsed: ParsedToolCall) -> dict[str, Any]:
        tool = self._tools.get(parsed.name)
        if tool is None:
            raise ParseError(f"Unknown tool: {parsed.name}")
        schema = getattr(tool, "schemas", lambda: [])()
        tool_schema = next((s for s in schema if s.get("function", {}).get("name") == parsed.name), None)
        if tool_schema:
            required = tool_schema.get("function", {}).get("parameters", {}).get("required", [])
            for field_name in required:
                if field_name not in parsed.arguments:
                    raise ParseError(f"Missing required argument: {field_name}")
        return parsed.arguments
