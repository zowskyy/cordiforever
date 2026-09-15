from __future__ import annotations

import tempfile
from pathlib import Path

from core.events import Event
from core.event_log import EventLog
from core.lifecycle import LifecycleConsolidator


def test_maybe_consolidate_skips_below_threshold():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            log.append(Event(type="user.message", session_id="s1", payload={"content": "hello"}))
            consolidator = LifecycleConsolidator(log, cluster_threshold=10)
            summaries = consolidator.maybe_consolidate("s1")
            assert summaries == []


def test_maybe_consolidate_produces_clusters():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            for i in range(5):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "arguments": {"path": "a.txt"}}))
            for i in range(5):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read", "arguments": {"path": "b.txt"}}))
            consolidator = LifecycleConsolidator(log, cluster_threshold=5)
            summaries = consolidator.maybe_consolidate("s1")
            assert len(summaries) >= 1
            topics = {s["topic"] for s in summaries}
            assert "file_write" in topics or "file_read" in topics


def test_cluster_summary_counts_tools_and_files():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            for i in range(3):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "arguments": {"path": "a.txt"}}))
            consolidator = LifecycleConsolidator(log, cluster_threshold=2)
            summaries = consolidator.maybe_consolidate("s1")
            assert len(summaries) == 1
            assert summaries[0]["event_count"] == 3
            assert "file_write" in summaries[0]["tools_used"]


def test_cluster_summary_includes_salience():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            for i in range(3):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "arguments": {"path": "a.txt"}, "success": False}))
            consolidator = LifecycleConsolidator(log, cluster_threshold=2)
            summaries = consolidator.maybe_consolidate("s1")
            assert len(summaries) == 1
            assert "salience" in summaries[0]
            assert summaries[0]["error_count"] == 3


def test_cluster_summary_includes_recurrence():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            for i in range(3):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "arguments": {"path": "a.txt"}}))
            for i in range(2):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_read", "arguments": {"path": "b.txt"}}))
            consolidator = LifecycleConsolidator(log, cluster_threshold=2)
            summaries = consolidator.maybe_consolidate("s1")
            file_write_summary = next((s for s in summaries if s["topic"] == "file_write"), None)
            assert file_write_summary is not None
            assert file_write_summary["recurrence"] == 3


def test_cluster_summary_includes_utility():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        with EventLog(db) as log:
            for i in range(3):
                log.append(Event(type="tool.result", session_id="s1", payload={"tool_name": "file_write", "arguments": {"path": "a.txt"}, "success": True}))
            consolidator = LifecycleConsolidator(log, cluster_threshold=2)
            summaries = consolidator.maybe_consolidate("s1")
            assert len(summaries) == 1
            assert summaries[0]["utility"] == 1.0
