from __future__ import annotations

import time

import pytest

from plugins.tools.run_command import RunCommand


@pytest.fixture
def cmd(tmp_path):
    tool = RunCommand(workspace=tmp_path)
    tool.start()
    yield tool
    tool.stop()


def test_run_command_echo(cmd):
    result = cmd.run("echo hello")
    assert result["success"] is True
    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


def test_run_command_non_zero_exit(cmd):
    result = cmd.run("exit 42")
    assert result["success"] is False
    assert result["returncode"] == 42


def test_run_command_captures_stderr(cmd):
    result = cmd.run("echo err >&2")
    assert result["success"] is True
    assert "err" in result["stderr"]


def test_run_command_includes_duration(cmd):
    result = cmd.run("echo fast")
    assert "duration_ms" in result
    assert result["duration_ms"] >= 0


def test_run_command_timeout(cmd):
    result = cmd.run("python -c \"import time; time.sleep(10)\"", timeout=2)
    assert result["success"] is False
    assert result["error"] == "timeout"


def test_run_command_workspace_cwd(cmd, tmp_path):
    (tmp_path / "workspace_marker.txt").write_text("x", encoding="utf-8")
    # Use python for cross-platform file read (cat is not available on Windows)
    result = cmd.run("python -c \"import sys; print(open('workspace_marker.txt').read())\"")
    assert result["success"] is True
    assert "x" in result["stdout"]


def test_run_command_emit_events(cmd):
    # Just verify it doesn't crash when context is missing
    result = cmd.run("echo no-context")
    assert result["success"] is True


def test_run_command_execute_schema(cmd):
    schemas = cmd.schemas()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "run_command"


def test_run_command_execute_dispatch(cmd):
    result = cmd.execute("run_command", {"command": "echo dispatched"})
    assert "dispatched" in result
    assert "[exit 0]" in result
