from __future__ import annotations

from pathlib import Path

import pytest

from core.messages import Message
from tests.failure_recovery.harness import (
    DeterministicSandbox,
    FaultInjectingModel,
    Scorecard,
    Task,
    summarize,
)


def test_task_creation():
    task = Task(
        name="write_file",
        user_input="create a file",
        model_responses=[],
        expected_output="done",
        fault_config={"model_errors": [2]},
        metadata={"difficulty": "easy"},
    )
    assert task.name == "write_file"
    assert task.fault_config["model_errors"] == [2]
    assert task.metadata["difficulty"] == "easy"


def test_scorecard_defaults():
    sc = Scorecard(task_name="test", seed=42, policy="retry")
    assert sc.task_success is False
    assert sc.invalid_call_rate == 0.0
    assert sc.recovery_rate == 0.0
    assert sc.budget_exhausted is False
    assert sc.error is None


def test_fault_injecting_model_normal_response():
    model = FaultInjectingModel([Message("assistant", "ok")])
    response = model.chat([], [])
    assert response.content == "ok"
    assert model.call_count == 1


def test_fault_injecting_model_error_on_call():
    model = FaultInjectingModel(
        [Message("assistant", "ok")],
        fault_config={"model_errors": [1]},
    )
    with pytest.raises(Exception, match="Simulated model error"):
        model.chat([], [])
    assert model.call_count == 1


def test_fault_injecting_model_malformed_response():
    model = FaultInjectingModel(
        [Message("assistant", "ok")],
        fault_config={"malformed_responses": [1]},
    )
    response = model.chat([], [])
    assert response.content == "This is not a valid JSON tool call"


def test_fault_injecting_tools_wrong_output(tmp_path):
    from tests.failure_recovery.harness import FaultInjectingTools
    tools = FaultInjectingTools(tmp_path, wrong_outputs={"read_file:missing.txt": "WRONG"})
    assert tools.read_file("missing.txt") == "WRONG"


def test_summarize_empty():
    assert summarize([]) == {}


def test_summarize():
    scorecards = [
        Scorecard(task_name="t1", seed=1, policy="retry", task_success=True),
        Scorecard(task_name="t2", seed=1, policy="retry", task_success=False),
    ]
    summary = summarize(scorecards)
    assert summary["tasks"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["budget_exhausted_count"] == 0
