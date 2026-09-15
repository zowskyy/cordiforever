from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.core.data_exporter import DataExporter


def test_data_exporter_delta_skips_old_sessions(tmp_path):
    exporter = DataExporter()
    exporter._event_log = None  # no event log => 0 exported
    count = exporter.export_successful_sessions(tmp_path, delta=True)
    assert count == 0


def test_data_exporter_saves_last_export_timestamp(tmp_path):
    exporter = DataExporter()
    exporter._state_file = tmp_path / "state.json"
    exporter._save_last_export_timestamp()
    assert exporter._state_file.exists()
    data = json.loads(exporter._state_file.read_text(encoding="utf-8"))
    assert "last_export_timestamp" in data


def test_data_exporter_loads_last_export_timestamp(tmp_path):
    exporter = DataExporter()
    ts = datetime.now(timezone.utc).isoformat()
    (tmp_path / "state.json").write_text(json.dumps({"last_export_timestamp": ts}), encoding="utf-8")
    exporter._state_file = tmp_path / "state.json"
    loaded = exporter._load_last_export_timestamp()
    assert loaded is not None
    assert loaded.isoformat() == ts


def test_data_exporter_load_last_export_missing_file(tmp_path):
    exporter = DataExporter()
    exporter._state_file = tmp_path / "missing.json"
    assert exporter._load_last_export_timestamp() is None


def test_data_exporter_delta_state_file_recreated_on_corrupt(tmp_path):
    exporter = DataExporter()
    exporter._state_file = tmp_path / "bad.json"
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    assert exporter._load_last_export_timestamp() is None
    exporter._save_last_export_timestamp()
    assert exporter._state_file.exists()
