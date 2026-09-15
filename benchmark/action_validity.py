"""Validate a raw model reply against the compact action JSON schema (anyOf branches with required args)."""

from __future__ import annotations

import json
from typing import Any


def action_violation(raw: str, response_format: dict[str, Any]) -> str | None:
    """Return None if `raw` is exactly one executable action, else a short reason."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return "not_json"
    if not isinstance(obj, dict) or set(obj) != {"tool", "args"}:
        return "wrong_shape"
    for branch in response_format.get("anyOf", []):
        if branch["properties"]["tool"]["const"] != obj["tool"]:
            continue
        spec = branch["properties"]["args"]
        args = obj["args"]
        if not isinstance(args, dict):
            return "args_not_object"
        missing = [k for k in spec.get("required", []) if not isinstance(args.get(k), str)]
        if missing:
            return f"missing:{','.join(missing)}"
        extra = set(args) - set(spec.get("properties", {}))
        if extra:
            return f"extra:{','.join(sorted(extra))}"
        return None
    return f"unknown_tool:{obj['tool']}"
