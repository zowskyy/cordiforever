from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class LintIssue:
    file: str
    line: int
    column: int
    severity: str  # "error" | "warning" | "info"
    rule_id: str
    message: str


@dataclass
class LintResult:
    file: str
    issues: list[LintIssue] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0

    @property
    def passed(self) -> bool:
        return self.error_count == 0


class LintingEngine:
    """Project-specific static analysis for Cordis-Lite."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or Path.cwd()
        self._rules = [
            self._check_plugin_subclass,
            self._check_event_driven_subscription,
            self._check_missing_super_init,
            self._check_hardcoded_tool_names,
            self._check_missing_type_annotations,
            self._check_import_from_core,
            self._check_emit_event_handler_wrapped,
            self._check_tool_schemas_method,
            self._check_agent_loop_schemas,
            self._check_context_builder_reality,
            self._check_event_logger_session,
        ]

    def lint_file(self, path: Path) -> LintResult:
        try:
            rel = str(path.relative_to(self.root))
        except ValueError:
            rel = str(path)
        result = LintResult(file=rel)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            result.issues.append(LintIssue(
                file=rel, line=1, column=1,
                severity="error", rule_id="parse_error",
                message=f"Failed to parse: {exc}",
            ))
            result.error_count += 1
            return result

        for rule in self._rules:
            try:
                rule(tree, path, source, result)
            except Exception:
                continue

        result.error_count = sum(1 for i in result.issues if i.severity == "error")
        result.warning_count = sum(1 for i in result.issues if i.severity == "warning")
        return result

    def lint_directory(self, directory: Path) -> LintResult:
        combined = LintResult(file=str(directory.relative_to(self.root) if directory.is_relative_to(self.root) else directory))
        for py in directory.rglob("*.py"):
            # Filter on parts RELATIVE to the linted dir: dot/__pycache__ ancestors
            # of the tree (e.g. a ".cache" or temp dir) must not silence linting.
            rel_parts = py.relative_to(directory).parts
            if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
                continue
            result = self.lint_file(py)
            combined.issues.extend(result.issues)
            combined.error_count += result.error_count
            combined.warning_count += result.warning_count
        return combined

    def _check_plugin_subclass(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [self._name(b) for b in node.bases]
                if "Plugin" in bases or "EventDrivenPlugin" in bases:
                    if not any(isinstance(item, ast.FunctionDef) and item.name == "start" for item in node.body):
                        result.issues.append(LintIssue(
                            file=result.file,
                            line=node.lineno, column=node.col_offset,
                            severity="warning", rule_id="plugin-missing-start",
                            message=f"Plugin subclass '{node.name}' should implement start()",
                        ))

    def _check_event_driven_subscription(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [self._name(b) for b in node.bases]
                if "EventDrivenPlugin" in bases:
                    has_subscribe = any(isinstance(item, ast.FunctionDef) and item.name == "_subscribe" for item in node.body)
                    if not has_subscribe:
                        result.issues.append(LintIssue(
                            file=result.file,
                            line=node.lineno, column=node.col_offset,
                            severity="warning", rule_id="event-driven-missing-subscribe",
                            message=f"EventDrivenPlugin subclass '{node.name}' should implement _subscribe()",
                        ))

    def _check_missing_super_init(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                        has_super = any(
                            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                            and isinstance(stmt.value.func, ast.Attribute)
                            and stmt.value.func.attr == "__init__"
                            for stmt in ast.walk(item)
                        )
                        if not has_super:
                            result.issues.append(LintIssue(
                                file=result.file,
                                line=item.lineno, column=item.col_offset,
                                severity="error", rule_id="missing-super-init",
                                message=f"__init__ in '{node.name}' does not call super().__init__()",
                            ))

    def _check_hardcoded_tool_names(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        tool_names = {"read_file", "write_file", "list_directory", "read_json"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in tool_names:
                    result.issues.append(LintIssue(
                        file=result.file,
                        line=node.lineno, column=node.col_offset,
                        severity="info", rule_id="hardcoded-tool-name",
                        message=f"Hardcoded tool name '{node.value}'. Consider using a constant or schema.",
                    ))

    def _check_missing_type_annotations(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        if "test" in str(path).lower():
            return
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                if not node.returns and not any(isinstance(a, ast.AnnAssign) for a in node.args.args):
                    result.issues.append(LintIssue(
                        file=result.file,
                        line=node.lineno, column=node.col_offset,
                        severity="info", rule_id="missing-type-annotation",
                        message=f"Public function '{node.name}' lacks type annotations",
                    ))

    def _check_import_from_core(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        if "plugins" not in path.parts:
            return
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("core."):
                    result.issues.append(LintIssue(
                        file=result.file,
                        line=node.lineno, column=node.col_offset,
                        severity="warning", rule_id="plugin-imports-core",
                        message=f"Plugin imports from core module '{node.module}'. Prefer composition via dependencies.",
                    ))

    def _check_emit_event_handler_wrapped(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in {"on_turn_start", "on_tool_result", "on_turn_end"}:
                has_try = any(isinstance(stmt, ast.Try) for stmt in node.body)
                if not has_try:
                    result.issues.append(LintIssue(
                        file=result.file,
                        line=node.lineno, column=node.col_offset,
                        severity="warning", rule_id="event-handler-unprotected",
                        message=f"Event handler '{node.name}' should wrap logic in try/except to avoid breaking the event bus",
                    ))

    def _check_tool_schemas_method(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [self._name(b) for b in node.bases]
                if "Plugin" in bases:
                    has_schemas = any(
                        isinstance(item, ast.FunctionDef) and item.name == "schemas"
                        for item in node.body
                    )
                    if not has_schemas and "tool" in node.name.lower():
                        result.issues.append(LintIssue(
                         file=result.file,
                         line=node.lineno, column=node.col_offset,
                         severity="warning", rule_id="event-handler-unprotected",
                         message=f"Event handler '{node.name}' should wrap logic in try/except to avoid breaking the event bus",
                     ))

    def _check_agent_loop_schemas(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "AgentLoop":
                has_schemas_populated = False
                for item in ast.walk(node):
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Attribute) and target.attr == "_tool_schemas":
                                has_schemas_populated = True
                if not has_schemas_populated:
                    result.issues.append(LintIssue(
                        file=result.file, line=node.lineno, column=node.col_offset,
                        severity="warning", rule_id="agent-loop-missing-tool-schemas",
                        message="AgentLoop should populate _tool_schemas in start()"
                    ))

    def _check_context_builder_reality(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "ContextBuilderPlugin":
                deps = getattr(node, "dependencies", ())
                if isinstance(deps, (list, tuple)) and "reality_projector" not in deps:
                    result.issues.append(LintIssue(
                        file=result.file, line=node.lineno, column=node.col_offset,
                        severity="warning", rule_id="context-builder-missing-reality",
                        message="ContextBuilderPlugin should depend on reality_projector"
                    ))

    def _check_event_logger_session(self, tree: ast.AST, path: Path, source: str, result: LintResult) -> None:
        if not isinstance(tree, ast.Module):
            return
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "EventLogger":
                has_session_emit = "session.start" in source
                if not has_session_emit:
                    result.issues.append(LintIssue(
                        file=result.file, line=node.lineno, column=node.col_offset,
                        severity="warning", rule_id="event-logger-missing-session",
                        message="EventLogger should emit session.start event"
                    ))

    @staticmethod
    def _name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""
