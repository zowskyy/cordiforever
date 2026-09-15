from __future__ import annotations

import pytest

from core.failure_taxonomy import FailureTaxonomy, FailureType
from core.self_healing import BudgetedSelfHealing


def test_classify_argument_error():
    taxonomy = FailureTaxonomy()
    error = TypeError("Malformed tool arguments")
    result = taxonomy.classify(error, {})
    assert result == FailureType.ARGUMENT


def test_classify_transient_error():
    taxonomy = FailureTaxonomy()
    error = RuntimeError("Tool execution failed")
    result = taxonomy.classify(error, {})
    assert result == FailureType.TRANSIENT


def test_classify_timeout():
    taxonomy = FailureTaxonomy()
    error = TimeoutError("Tool timed out")
    result = taxonomy.classify(error, {})
    assert result == FailureType.TRANSIENT


def test_recovery_action_mapping():
    assert FailureTaxonomy.recovery_action(FailureType.ARGUMENT) == "retry"
    assert FailureTaxonomy.recovery_action(FailureType.TRANSIENT) == "retry"
    assert FailureTaxonomy.recovery_action(FailureType.TOOL_SELECTION) == "replan"
    assert FailureTaxonomy.recovery_action(FailureType.SEMANTIC_VERIFICATION) == "cross_check"
    assert FailureTaxonomy.recovery_action(FailureType.UNKNOWN) == "abstain"


def test_self_healing_bounded_retry():
    healer = BudgetedSelfHealing(max_retries=2)
    result = healer.handle_failure(FailureType.ARGUMENT, {"tool_name": "file_read"})
    assert result["action"] == "retry"
    assert result["attempt"] == 1


def test_self_healing_retry_budget_exhausted():
    healer = BudgetedSelfHealing(max_retries=2)
    healer.handle_failure(FailureType.ARGUMENT, {"tool_name": "file_read"})
    healer.handle_failure(FailureType.ARGUMENT, {"tool_name": "file_read"})
    result = healer.handle_failure(FailureType.ARGUMENT, {"tool_name": "file_read"})
    assert result["action"] == "abstain"
    assert result["reason"] == "retry_budget_exhausted"


def test_self_healing_replan():
    healer = BudgetedSelfHealing(max_replans=1)
    result = healer.handle_failure(FailureType.TOOL_SELECTION, {"task_id": "task-1"})
    assert result["action"] == "replan"
    assert result["attempt"] == 1


def test_self_healing_cross_check():
    healer = BudgetedSelfHealing()
    result = healer.handle_failure(FailureType.SEMANTIC_VERIFICATION, {"sources": ["source1", "source2"]})
    assert result["action"] == "cross_check"
    assert result["instruction"] == "Verify output against alternative source"


def test_self_healing_escalate():
    healer = BudgetedSelfHealing(max_replans=1)
    healer.handle_failure(FailureType.TOOL_SELECTION, {"task_id": "task-1"})
    result = healer.handle_failure(FailureType.TOOL_SELECTION, {"task_id": "task-1"})
    assert result["action"] == "escalate"