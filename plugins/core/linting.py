from __future__ import annotations

from pathlib import Path
from typing import Any

from core.linting import LintingEngine, LintResult
from core.plugin import EventDrivenPlugin


class LintingPlugin(EventDrivenPlugin):
    name = "linting"
    dependencies = ()

    def __init__(self, root: Path | None = None) -> None:
        super().__init__()
        self.root = root or Path.cwd()
        self._engine = LintingEngine(root=self.root)

    def start(self) -> None:
        pass

    def lint_path(self, path: Path) -> LintResult:
        if path.is_file():
            return self._engine.lint_file(path)
        if path.is_dir():
            return self._lint_directory(path)
        from core.linting import LintResult
        return LintResult(file=str(path))

    def _lint_directory(self, directory: Path) -> LintResult:
        combined = LintResult(file=str(directory.relative_to(self.root)))
        for py in directory.rglob("*.py"):
            if any(part.startswith(".") or part == "__pycache__" for part in py.parts):
                continue
            result = self._engine.lint_file(py)
            combined.issues.extend(result.issues)
            combined.error_count += result.error_count
            combined.warning_count += result.warning_count
        return combined

    def on_turn_end(self, event: Any) -> None:
        payload = event.payload if hasattr(event, "payload") else {}
        if payload.get("final_result") == "" and payload.get("error") == "max_rounds_exceeded":
            self.emit_turn_lint(event)

    def emit_turn_lint(self, event: Any) -> None:
        if self.context is None:
            return
        session_id = getattr(event, "session_id", "")
        self.context.events.emit("lint.warning", {
            "session_id": session_id,
            "rule_id": "agent-max-rounds-exceeded",
            "message": "Agent exceeded maximum rounds. Consider increasing max_rounds or reviewing tool-call parsing.",
        })
