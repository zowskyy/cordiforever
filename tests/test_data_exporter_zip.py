"""Tests for DataExporter session ZIP export."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.core.data_exporter import DataExporter
from core.events import Event


def _make_exporter(tmp_path: Path):
    exporter = DataExporter()
    exporter._event_log = MagicMock()
    exporter._event_log.get_session_events.return_value = [
        Event(type="user.message", session_id="s1", payload={"content": "hi"}),
        Event(type="assistant.message", session_id="s1", payload={"content": "hello"}),
    ]
    exporter._event_log.query.return_value = []
    exporter._run_state = {}
    return exporter


def test_export_session_zip_creates_zip(tmp_path: Path):
    exporter = _make_exporter(tmp_path)
    out = tmp_path / "session_s1.zip"
    assert exporter.export_session_zip("s1", out) is True
    assert out.exists()
    with zipfile.ZipFile(out, "r") as zf:
        names = zf.namelist()
        assert "s1/events.jsonl" in names
        assert "s1/metadata.json" in names
        events = zf.read("s1/events.jsonl").decode("utf-8").splitlines()
        assert len(events) == 2
        meta = json.loads(zf.read("s1/metadata.json").decode("utf-8"))
        assert meta["session_id"] == "s1"


def test_export_session_zip_returns_false_without_event_log(tmp_path: Path):
    exporter = DataExporter()
    exporter._event_log = None
    assert exporter.export_session_zip("s1", tmp_path / "out.zip") is False
