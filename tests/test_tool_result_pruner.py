"""Tests for the ToolResultPruner plugin."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.core.tool_result_pruner import ToolResultPruner


def _make_context(tmp_path: Path, config_overrides: dict[str, str] | None = None) -> MagicMock:
    ctx = MagicMock()
    config = {"profile": "lite", "tool_result_pruner.spill_dir": str(tmp_path / "spilled")}
    if config_overrides:
        config.update(config_overrides)
    ctx.config = config
    ctx.plugins = {}
    ctx.events = MagicMock()
    ctx.events.emit = MagicMock()
    return ctx


def test_tool_result_pruner_registers_name():
    plugin = ToolResultPruner()
    assert plugin.name == "tool_result_pruner"


def test_tool_result_pruner_does_not_prune_short_result(tmp_path: Path):
    plugin = ToolResultPruner()
    plugin.context = _make_context(tmp_path)
    plugin.start()
    result, pruned, spill = plugin.prune("read_file", "call_1", "short result")
    assert result == "short result"
    assert pruned is False
    assert spill is None


def test_tool_result_pruner_prunes_long_result(tmp_path: Path):
    plugin = ToolResultPruner()
    plugin.context = _make_context(tmp_path, {"tool_result_pruner.threshold_chars": "10", "tool_result_pruner.head_chars": "5", "tool_result_pruner.tail_chars": "3"})
    plugin.start()
    long_result = "0123456789abcdef"
    result, pruned, spill = plugin.prune("read_file", "call_2", long_result)
    assert pruned is True
    assert "truncated" in result
    assert result.startswith("01234")
    assert result.endswith("def")
    assert spill is not None
    assert Path(spill).exists()
    assert Path(spill).read_text(encoding="utf-8") == long_result


def test_tool_result_pruner_emits_events(tmp_path: Path):
    plugin = ToolResultPruner()
    plugin.context = _make_context(tmp_path, {"tool_result_pruner.threshold_chars": "10", "tool_result_pruner.head_chars": "5", "tool_result_pruner.tail_chars": "3"})
    plugin.start()
    plugin.prune("read_file", "call_3", "0123456789abcdef")
    assert plugin.context.events.emit.call_count == 2
    calls = [call.args[0] for call in plugin.context.events.emit.call_args_list]
    assert "tool.result.pruned" in calls
    assert "tool.result.spilled" in calls


def test_tool_result_pruner_handles_bad_config(tmp_path: Path):
    plugin = ToolResultPruner()
    plugin.context = _make_context(tmp_path, {"tool_result_pruner.threshold_chars": "not-a-number"})
    plugin.start()
    # Should fall back to default threshold and not prune short strings.
    result, pruned, _ = plugin.prune("read_file", "call_4", "hi")
    assert result == "hi"
    assert pruned is False
