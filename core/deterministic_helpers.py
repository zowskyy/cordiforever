from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def count_chars(text: str, char: str) -> int:
    if not isinstance(char, str) or len(char) != 1:
        raise ValueError("char must be a single character")
    return sum(1 for c in text if c == char)


def validate_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def validate_semver(value: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", value))


def normalize_path(path: str) -> str:
    return str(Path(path).as_posix()).strip()


def normalize_identifier(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_").lower()


def count_pattern_occurrences(text: str, pattern: str) -> int:
    if not pattern:
        return 0
    return text.count(pattern)


def validate_json_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    for key, expected_type in schema.items():
        if key not in data:
            issues.append(f"missing key: {key}")
            continue
        value = data[key]
        type_name = expected_type.get("type", "any")
        if type_name == "string" and not isinstance(value, str):
            issues.append(f"{key}: expected string, got {type(value).__name__}")
        elif type_name == "int" and not isinstance(value, int):
            issues.append(f"{key}: expected int, got {type(value).__name__}")
        elif type_name == "bool" and not isinstance(value, bool):
            issues.append(f"{key}: expected bool, got {type(value).__name__}")
        elif type_name == "list" and not isinstance(value, list):
            issues.append(f"{key}: expected list, got {type(value).__name__}")
        elif type_name == "dict" and not isinstance(value, dict):
            issues.append(f"{key}: expected dict, got {type(value).__name__}")
    return issues


def compare_strings_exact(actual: str, expected: str) -> Dict[str, Any]:
    return {
        "equal": actual == expected,
        "actual_length": len(actual),
        "expected_length": len(expected),
        "diff_at": next((i for i, (a, e) in enumerate(zip(actual, expected)) if a != e), None),
    }
