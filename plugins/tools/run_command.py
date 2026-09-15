"""Sandboxed command execution plugin for Cordi v2.

Executes shell commands within the workspace directory with:
- cwd restriction to workspace
- output capture
- timeout enforcement
- event emission for tool lifecycle
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from core.plugin import Plugin


class RunCommand(Plugin):
    name = "run_command"
    dependencies = ()

    __contract__ = {
        "version": "1.0",
        "provides": ("command_execution",),
        "requires": (),
        "deterministic": True,
        "zero_token": True,
    }

    def __init__(self, workspace: str | Path | None = None, *, timeout: int = 30) -> None:
        super().__init__()
        self._workspace = Path(workspace).expanduser().resolve() if workspace else None
        self._timeout = timeout
        self._session_id: str | None = None

    def start(self) -> None:
        if self._workspace is None and self.context is not None:
            self._workspace = Path(self.context.config.get("workspace", ".")).expanduser().resolve()
        if self._workspace is not None:
            self._workspace.mkdir(parents=True, exist_ok=True)
        if self.context is not None:
            self._session_id = self._get_session_id()

    def stop(self) -> None:
        self._session_id = None

    def health_check(self) -> dict[str, Any]:
        return {
            "healthy": self._workspace is not None and self._workspace.exists(),
            "workspace": str(self._workspace) if self._workspace else None,
            "timeout": self._timeout,
        }

    def run(self, command: str, *, timeout: int | None = None) -> dict[str, Any]:
        """Execute a command in the workspace directory.

        Args:
            command: Shell command to execute.
            timeout: Optional timeout override in seconds.

        Returns:
            Dict with stdout, stderr, returncode, duration_ms, success.
        """
        if not command or not command.strip():
            raise ValueError("command must be a non-empty string")
        if self._workspace is None:
            raise RuntimeError("RunCommand workspace is not configured")

        effective_timeout = timeout or self._timeout
        call_id = self._emit_call_start(command)

        start = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            result = {
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "returncode": completed.returncode,
                "duration_ms": round(duration_ms, 3),
                "success": completed.returncode == 0,
                "command": command,
                "call_id": call_id,
            }
            self._emit_call_end(call_id, result)
            return result
        except subprocess.TimeoutExpired as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            result = {
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "returncode": -1,
                "duration_ms": round(duration_ms, 3),
                "success": False,
                "error": "timeout",
                "command": command,
                "call_id": call_id,
            }
            self._emit_call_end(call_id, result)
            return result
        except OSError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            result = {
                "stdout": "",
                "stderr": str(exc),
                "returncode": -1,
                "duration_ms": round(duration_ms, 3),
                "success": False,
                "error": "os_error",
                "command": command,
                "call_id": call_id,
            }
            self._emit_call_end(call_id, result)
            return result

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Execute a shell command in the workspace directory. Output is captured and returned.",
                    "parameters": {
                        "type": "object",
                        "required": ["command"],
                        "properties": {
                            "command": {"type": "string", "description": "Shell command to execute."},
                            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)."},
                        },
                    },
                },
            }
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "run_command":
            raise ValueError(f"Unknown tool: {name}")
        command = str(arguments.get("command", "")).strip()
        timeout = arguments.get("timeout")
        result = self.run(command, timeout=int(timeout) if timeout else None)
        parts = []
        if result.get("stdout"):
            parts.append(result["stdout"].rstrip())
        if result.get("stderr"):
            parts.append("STDERR: " + result["stderr"].rstrip())
        parts.append(f"[exit {result['returncode']}]")
        return "\n".join(parts)

    def _get_session_id(self) -> str:
        event_logger = self.context.plugins.get("event_logger") if self.context else None
        if event_logger is not None and hasattr(event_logger, "continuity"):
            return getattr(event_logger.continuity, "session_id", "unknown")
        return "unknown"

    def _emit_call_start(self, command: str) -> str:
        call_id = f"cmd_{id(command)}_{int(time.time() * 1000)}"
        if self.context is not None:
            try:
                self.context.events.emit("tool.call.start", {
                    "tool_name": "run_command",
                    "call_id": call_id,
                    "command": command,
                    "session_id": self._session_id,
                })
            except Exception:
                pass
        return call_id

    def _emit_call_end(self, call_id: str, result: dict[str, Any]) -> None:
        if self.context is not None:
            try:
                self.context.events.emit("tool.call.end", {
                    "tool_name": "run_command",
                    "call_id": call_id,
                    "session_id": self._session_id,
                    "result": result,
                })
            except Exception:
                pass
