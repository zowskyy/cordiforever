"""Benchmark tests for ArrayHelper evaluation.

These tests verify the benchmark infrastructure works correctly and
measure ArrayHelper's impact on array tasks.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tests.benchmarks.tasks import ALL_ARRAY_TASKS, ArrayTask, get_tasks_by_tag
from tests.benchmarks.runner import run_benchmark_suite, run_task


def test_benchmark_tasks_defined():
    """At least 10 array tasks should be defined."""
    assert len(ALL_ARRAY_TASKS) >= 10


def test_benchmark_tasks_cover_all_operations():
    """Tasks should cover filter, sort, update, delete, aggregate."""
    tags = set()
    for task in ALL_ARRAY_TASKS:
        tags.update(task.tags)
    assert "filter" in tags
    assert "sort" in tags
    assert "update" in tags
    assert "delete" in tags
    assert "aggregate" in tags


def test_get_tasks_by_tag():
    """get_tasks_by_tag should return filtered results."""
    filter_tasks = get_tasks_by_tag("filter")
    assert len(filter_tasks) > 0
    for t in filter_tasks:
        assert "filter" in t.tags


def test_task_source_content_has_valid_js():
    """All task source content should be valid JavaScript-ish content."""
    for task in ALL_ARRAY_TASKS:
        assert task.source_content.strip(), f"Task {task.name} has empty source content"
        assert task.source_file.endswith(".js"), f"Task {task.name} source file should be .js"


def test_task_verify_functions_are_callable():
    """All verify functions should be callable."""
    for task in ALL_ARRAY_TASKS:
        assert callable(task.verify), f"Task {task.name} verify function not callable"


def test_benchmark_runner_result_structure(tmp_path):
    """Runner should return a properly structured result."""
    task = ALL_ARRAY_TASKS[0]
    result = run_task(task, tmp_path, enable_array_helper=False)
    assert result.task_name == task.name
    assert result.array_helper_enabled is False
    assert isinstance(result.completed, bool)
    assert isinstance(result.model_turns, int)
    assert isinstance(result.tool_calls, int)


def test_benchmark_runner_with_helper(tmp_path):
    """Runner should execute tasks with ArrayHelper enabled."""
    task = ALL_ARRAY_TASKS[0]
    result = run_task(task, tmp_path, enable_array_helper=True)
    assert result.task_name == task.name
    assert result.array_helper_enabled is True
    assert isinstance(result.completed, bool)


def test_benchmark_suite_generates_report(tmp_path):
    """Full benchmark suite should produce a structured report."""
    tasks = ALL_ARRAY_TASKS[:3]
    report = run_benchmark_suite(tasks, runs_per_task=1)

    assert "total_tasks" in report
    assert "with_helper" in report
    assert "without_helper" in report
    assert "completion_rate" in report["with_helper"]
    assert "avg_model_turns" in report["with_helper"]
    assert "avg_tool_calls" in report["with_helper"]
    assert "per_task" in report
    assert len(report["per_task"]) == 6  # 3 tasks × 2 (with/without)


def test_benchmark_zero_drag_without_helper(tmp_path):
    """Without ArrayHelper should show zero token overhead."""
    task = ALL_ARRAY_TASKS[0]
    result = run_task(task, tmp_path, enable_array_helper=False)
    assert result.token_overhead_estimate == 0
