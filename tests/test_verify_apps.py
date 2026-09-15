from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_apps import run_verification, write_json_report, write_markdown_report


def test_run_verification_empty_workspace(tmp_path):
    report = run_verification(tmp_path, "build a todo app")
    assert "results" in report
    assert report["criteria_count"] > 0


def test_write_json_report(tmp_path):
    report = {
        "workspace": str(tmp_path),
        "user_request": "test",
        "timestamp": "2025-01-01T00:00:00Z",
        "passed": True,
        "criteria_count": 2,
        "failed_count": 0,
        "results": [],
        "feedback": "All verification checks passed.",
    }
    out = write_json_report(report, tmp_path)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["passed"] is True


def test_write_markdown_report(tmp_path):
    report = {
        "workspace": str(tmp_path),
        "user_request": "test",
        "timestamp": "2025-01-01T00:00:00Z",
        "passed": False,
        "criteria_count": 1,
        "failed_count": 1,
        "results": [
            {
                "name": "todo_html_exists",
                "check_type": "file_exists",
                "required": True,
                "passed": False,
                "evidence": "file_exists:index.html=False",
                "feedback": "File does not exist: index.html",
            }
        ],
        "feedback": "Verification failed.",
    }
    out = write_markdown_report(report, tmp_path)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "# App Verification Report" in text
    assert "FAILED" in text
    assert "todo_html_exists" in text
