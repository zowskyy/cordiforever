from __future__ import annotations

from typing import Any

from .failure_taxonomy import FailureTaxonomy, FailureType


class BudgetedSelfHealing:
    """Maps failure classes to recovery actions with budget limits."""

    def __init__(self, max_retries: int = 3, max_replans: int = 2) -> None:
        self.max_retries = max_retries
        self.max_replans = max_replans
        self._retry_counts: dict[str, int] = {}
        self._replan_counts: dict[str, int] = {}

    def handle_failure(self, failure_type: FailureType, context: dict[str, Any]) -> dict[str, Any]:
        action = FailureTaxonomy.RECOVERY_ACTIONS.get(failure_type, "abstain")
        context.setdefault("failure_type", failure_type.value)

        if action == "retry":
            return self._bounded_retry(failure_type, context)
        if action == "replan":
            return self._bounded_replan(failure_type, context)
        if action == "cross_check":
            return self._cross_check(context)
        if action == "escalate":
            return {"action": "escalate", "reason": failure_type.value}
        return {"action": "abstain", "reason": failure_type.value}

    def _bounded_retry(self, failure_type: FailureType, context: dict[str, Any]) -> dict[str, Any]:
        key = context.get("tool_name", "unknown")
        count = self._retry_counts.get(key, 0)
        if count < self.max_retries:
            self._retry_counts[key] = count + 1
            return {"action": "retry", "attempt": count + 1, "max": self.max_retries}
        return {"action": "abstain", "reason": "retry_budget_exhausted"}

    def _bounded_replan(self, failure_type: FailureType, context: dict[str, Any]) -> dict[str, Any]:
        key = context.get("task_id", "default")
        count = self._replan_counts.get(key, 0)
        if count < self.max_replans:
            self._replan_counts[key] = count + 1
            return {"action": "replan", "attempt": count + 1, "max": self.max_replans}
        return {"action": "escalate", "reason": "replan_budget_exhausted"}

    def _cross_check(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "action": "cross_check",
            "sources": context.get("sources", []),
            "instruction": "Verify output against alternative source",
        }
