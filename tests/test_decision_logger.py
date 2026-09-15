from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.core.decision_logger import DecisionLogger


def test_decision_logger_logs_to_jsonl(tmp_path):
    from unittest.mock import MagicMock
    logger = DecisionLogger(log_dir=tmp_path)
    logger.context = MagicMock()  # bypass context check
    logger.set_session_id("session-1")
    logger.log_decision(
        decision_type="tool_selection",
        input_data={"tool": "read_file", "args": {"path": "a.txt"}},
        output_data="hello world",
        confidence=1.0,
        duration_ms=12.5,
    )
    log_file = tmp_path / f"decisions_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    assert log_file.exists()
    with open(log_file, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["session_id"] == "session-1"
    assert entry["decision_type"] == "tool_selection"
    assert entry["confidence"] == 1.0
    assert entry["duration_ms"] == 12.5


def test_decision_logger_increments_turn():
    logger = DecisionLogger()
    logger.set_session_id("s1")
    assert logger.increment_turn() == 1
    assert logger.increment_turn() == 2
    assert logger.increment_turn() == 3


def test_decision_logger_skips_when_disabled(tmp_path):
    logger = DecisionLogger(log_dir=tmp_path)
    logger._enabled = False
    logger.set_session_id("s1")
    logger.log_decision("routing", "input", "output")
    log_file = tmp_path / f"decisions_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    assert not log_file.exists()


def test_decision_logger_handles_oserror(tmp_path):
    logger = DecisionLogger(log_dir=tmp_path)
    logger.set_session_id("s1")
    # Simulate unwritable dir by passing a file as log_dir
    logger._log_dir = tmp_path / "file.txt"
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    logger.log_decision("routing", "input", "output")  # should not raise


def test_decision_logger_health_check():
    logger = DecisionLogger()
    health = logger.health_check()
    assert health["healthy"] is True
    assert health["plugin"] == "decision_logger"
