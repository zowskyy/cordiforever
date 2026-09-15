from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from plugins.core.formal_contracts import FormalContractsPlugin
from plugins.core.linting import LintingPlugin
from plugins.tools.file import FileTools


def test_formal_contracts_validates_missing_attribute(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=tmp_path)
    reg.register_class(LintingPlugin, root=tmp_path)
    reg.register_class(FormalContractsPlugin)
    reg.start_all()
    fc = ctx.plugins["formal_contracts"]
    fc.register_contract("file_tools", {
        "required_attributes": ["workspace", "nonexistent_attr"],
        "required_methods": [],
    })
    violations = fc.validate_plugin("file_tools", ctx.plugins["file_tools"])
    assert any(v.rule_id == "missing-attribute" for v in violations)


def test_formal_contracts_validates_missing_method(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=tmp_path)
    reg.register_class(LintingPlugin, root=tmp_path)
    reg.register_class(FormalContractsPlugin)
    reg.start_all()
    fc = ctx.plugins["formal_contracts"]
    fc.register_contract("file_tools", {
        "required_attributes": [],
        "required_methods": ["nonexistent_method"],
    })
    violations = fc.validate_plugin("file_tools", ctx.plugins["file_tools"])
    assert any(v.rule_id == "missing-method" for v in violations)


def test_formal_contracts_emits_violation_event(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    reg.register_class(FileTools, workspace=tmp_path)
    reg.register_class(LintingPlugin, root=tmp_path)
    reg.register_class(FormalContractsPlugin)
    reg.start_all()
    fc = ctx.plugins["formal_contracts"]
    fc.register_contract("file_tools", {
        "required_attributes": ["nonexistent_attr"],
        "required_methods": [],
    })
    events = []
    def capture(event):
        events.append(event)
    ctx.events.on("contract.violation", capture)
    fc.validate_all()
    assert any(e.payload.get("rule_id") == "missing-attribute" for e in events)
