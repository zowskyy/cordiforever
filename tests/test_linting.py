from __future__ import annotations

from pathlib import Path

import pytest

from core.linting import LintingEngine, LintResult, LintIssue


def _write_temp(source: str, suffix=".py") -> Path:
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        f.write(source)
        return Path(f.name)


def test_lint_plugin_missing_start():
    engine = LintingEngine(root=Path.cwd())
    path = _write_temp("""
from core.plugin import Plugin

class BadPlugin(Plugin):
    name = "bad"
""")
    try:
        result = engine.lint_file(path)
        assert any(issue.rule_id == "plugin-missing-start" for issue in result.issues)
    finally:
        path.unlink()


def test_lint_event_driven_missing_subscribe():
    engine = LintingEngine(root=Path.cwd())
    path = _write_temp("""
from core.plugin import EventDrivenPlugin

class BadEventPlugin(EventDrivenPlugin):
    name = "bad"
""")
    try:
        result = engine.lint_file(path)
        assert any(issue.rule_id == "event-driven-missing-subscribe" for issue in result.issues)
    finally:
        path.unlink()


def test_lint_missing_super_init():
    engine = LintingEngine(root=Path.cwd())
    path = _write_temp("""
class BadInit:
    def __init__(self, x):
        self.x = x
""")
    try:
        result = engine.lint_file(path)
        assert any(issue.rule_id == "missing-super-init" for issue in result.issues)
    finally:
        path.unlink()


def test_lint_valid_plugin():
    engine = LintingEngine(root=Path.cwd())
    path = _write_temp("""
from core.plugin import Plugin

class GoodPlugin(Plugin):
    name = "good"

    def __init__(self):
        super().__init__()

    def start(self):
        pass
""")
    try:
        result = engine.lint_file(path)
        assert not any(issue.rule_id == "plugin-missing-start" for issue in result.issues)
        assert not any(issue.rule_id == "missing-super-init" for issue in result.issues)
    finally:
        path.unlink()


def test_lint_hardcoded_tool_name():
    engine = LintingEngine(root=Path.cwd())
    path = _write_temp('TOOL = "write_file"')
    try:
        result = engine.lint_file(path)
        assert any(issue.rule_id == "hardcoded-tool-name" for issue in result.issues)
    finally:
        path.unlink()


def test_lint_plugin_imports_core():
    engine = LintingEngine(root=Path.cwd())
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plugins_dir = root / "plugins" / "core"
        plugins_dir.mkdir(parents=True)
        target = plugins_dir / "bad.py"
        target.write_text("from core.something import Foo\n", encoding="utf-8")
        result = engine.lint_file(target)
        assert any(issue.rule_id == "plugin-imports-core" for issue in result.issues)


def test_lint_directory():
    engine = LintingEngine(root=Path.cwd())
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "good.py").write_text("class GoodPlugin:\n    pass\n", encoding="utf-8")
        (root / "bad.py").write_text("class Bad:\n    def __init__(self): pass\n", encoding="utf-8")
        result = engine.lint_directory(root)
        assert result.error_count >= 1


def test_lint_directory_under_dot_prefixed_path():
    """Regression: a dot-prefixed ANCESTOR (e.g. .pytest_tmp) of the linted dir
    must not silence linting — the skip filter applies to parts inside the tree."""
    import shutil
    import tempfile
    engine = LintingEngine(root=Path.cwd())
    tmp = Path(tempfile.mkdtemp(prefix=".lintdot_"))
    try:
        (tmp / "bad.py").write_text("class Bad:\n    def __init__(self): pass\n", encoding="utf-8")
        result = engine.lint_directory(tmp)
        assert result.error_count >= 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
