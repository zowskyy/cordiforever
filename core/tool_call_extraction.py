from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def _stable_id(text: str) -> str:
    return f"{hashlib.md5(text.encode()).hexdigest()[:8]}"


def _dispatcher_names(tools: list[dict[str, Any]]) -> tuple[str, set[str]] | None:
    for t in tools:
        fn = t.get("function", {}) if isinstance(t, dict) else {}
        enum = fn.get("parameters", {}).get("properties", {}).get("tool", {}).get("enum")
        if fn.get("name") and isinstance(enum, list) and enum:
            return fn["name"], {str(e) for e in enum}
    return None


def _dispatcher_call(obj: Any, dispatcher: tuple[str, set[str]] | None) -> dict[str, Any] | None:
    """Wrap a bare logical call ({"tool": "read", "args": {...}} or {"name": "read", "arguments": {...}})."""
    if dispatcher is None or not isinstance(obj, dict):
        return None
    name, logical = dispatcher
    if isinstance(obj.get("function"), dict):
        obj = obj["function"]
    logical_name = obj.get("tool") if obj.get("tool") in logical else obj.get("name") if obj.get("name") in logical else None
    if logical_name is None:
        return None
    args = obj.get("args", obj.get("arguments", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    if "tool" in args and args.get("tool") == logical_name and isinstance(args.get("args"), dict):
        args = args["args"]
    raw = json.dumps({"tool": logical_name, "args": args}, sort_keys=True)
    return {"id": f"call_{_stable_id(raw)}", "type": "function", "function": {"name": name, "arguments": {"tool": logical_name, "args": args}}}


def extract_tool_calls_from_text(text: str, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_names = [t.get("function", {}).get("name", "") for t in tools if isinstance(t, dict)]
    if not tool_names:
        return []

    calls: list[dict[str, Any]] = []
    dispatcher = _dispatcher_names(tools)

    cleaned = text.strip()
    cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'```', '', cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "tool_calls" in parsed:
            for tc in parsed["tool_calls"]:
                if isinstance(tc, dict) and tc.get("function", {}).get("name") in tool_names:
                    calls.append(tc)
                elif (wrapped := _dispatcher_call(tc, dispatcher)) is not None:
                    calls.append(wrapped)
            if calls:
                return calls[:5]
    except (json.JSONDecodeError, ValueError):
        pass

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(cleaned):
        start = cleaned.find('{', idx)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(cleaned, start)
            if isinstance(obj, dict) and "tool_calls" in obj:
                for tc in obj["tool_calls"] if isinstance(obj["tool_calls"], list) else []:
                    if isinstance(tc, dict) and tc.get("function", {}).get("name") in tool_names:
                        calls.append(tc)
                    elif (wrapped := _dispatcher_call(tc, dispatcher)) is not None:
                        calls.append(wrapped)
                if calls:
                    return calls[:5]
            elif (wrapped := _dispatcher_call(obj, dispatcher)) is not None:
                return [wrapped]
            idx = end
        except (json.JSONDecodeError, ValueError):
            idx = start + 1

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "name" in parsed and "arguments" in parsed:
            name = parsed.get("name", "")
            if name in tool_names:
                calls.append({
                    "id": f"call_{_stable_id(cleaned)}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": parsed.get("arguments", {}),
                    }
                })
                return calls[:5]
    except (json.JSONDecodeError, ValueError):
        pass

    for name in tool_names:
        if not name:
            continue
        patterns = [
            re.compile(rf'{re.escape(name)}\s*\(\s*(\{{.*?\}})\s*\)', re.DOTALL | re.IGNORECASE),
            re.compile(rf'{re.escape(name)}\s*\(\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^)]*)\s*\)', re.IGNORECASE),
            re.compile(rf'"{re.escape(name)}"\s*\(\s*(\{{.*?\}})\s*\)', re.DOTALL | re.IGNORECASE),
            re.compile(r'"' + re.escape(name) + r'"\s*:\s*(\{.*?\})', re.DOTALL | re.IGNORECASE),
        ]
        for pattern in patterns:
            for match in pattern.finditer(text):
                args_str = match.group(1).strip()
                args = _parse_args_str(args_str)
                calls.append({
                    "id": f"call_{_stable_id(match.group(0))}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": args,
                    }
                })

    return calls[:5]


def _parse_args_str(args_str: str) -> dict[str, Any]:
    args_str = args_str.strip()
    if not args_str:
        return {}
    if args_str.startswith("{"):
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            pass
    if args_str.startswith('"') and args_str.endswith('"'):
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            return {"input": args_str.strip('"')}
    return {"input": args_str}
