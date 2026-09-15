from __future__ import annotations

import re
from enum import Enum
from typing import Any

from .errors import ModelError, ToolError


class FailureType(Enum):
    TRANSIENT = "transient"
    ARGUMENT = "argument"
    TOOL_SELECTION = "tool_selection"
    STALE_CONTEXT = "stale_context"
    SEMANTIC_VERIFICATION = "semantic_verification"
    UNKNOWN = "unknown"


class FailureClassifier:
    PATTERNS = {
        FailureType.TRANSIENT: ["timeout", "timed out", "connection refused", "network error", "socket", "busy", "retry"],
        FailureType.ARGUMENT: ["malformed", "invalid argument", "missing", "required", "type error", "validation", "schema"],
        FailureType.TOOL_SELECTION: ["unknown tool", "unsupported", "not found", "no such tool"],
        FailureType.STALE_CONTEXT: ["stale", "expired", "outdated", "version conflict"],
        FailureType.SEMANTIC_VERIFICATION: ["wrong output", "incorrect", "mismatch", "silent failure", "hallucination"],
    }

    @classmethod
    def classify(cls, error: Exception, context: dict[str, Any]) -> FailureType:
        message = str(error).lower()
        for failure_type, keywords in cls.PATTERNS.items():
            if any(k in message for k in keywords):
                return failure_type
        if isinstance(error, ToolError):
            return FailureType.ARGUMENT
        if isinstance(error, ModelError):
            return FailureType.TRANSIENT
        if isinstance(error, (TimeoutError, OSError, RuntimeError)):
            return FailureType.TRANSIENT
        return FailureType.UNKNOWN


class FailureTaxonomy:
    RECOVERY_ACTIONS: dict[FailureType, str] = {
        FailureType.TRANSIENT: "retry",
        FailureType.ARGUMENT: "retry",
        FailureType.TOOL_SELECTION: "replan",
        FailureType.STALE_CONTEXT: "replan",
        FailureType.SEMANTIC_VERIFICATION: "cross_check",
        FailureType.UNKNOWN: "abstain",
    }

    @classmethod
    def classify(cls, error: Exception, context: dict[str, Any]) -> FailureType:
        return FailureClassifier.classify(error, context)

    @classmethod
    def recovery_action(cls, failure_type: FailureType) -> str:
        return cls.RECOVERY_ACTIONS.get(failure_type, "abstain")


class PreFlightGuard:
    CHECKS = {
        "schema_valid": lambda args, schema: True,
        "not_repeated": lambda args, history: True,
        "no_conflict": lambda args, completed: True,
    }

    @classmethod
    def check(cls, tool_name: str, arguments: dict[str, Any], context: dict[str, Any]) -> list[str]:
        flags = []
        if not isinstance(arguments, dict):
            flags.append("invalid_schema")
        if context.get("recent_tool_calls", []):
            last = context["recent_tool_calls"][-1]
            if last.get("tool") == tool_name and last.get("arguments") == arguments:
                flags.append("repeated_call")
        return flags
