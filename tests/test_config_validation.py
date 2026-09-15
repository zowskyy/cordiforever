from __future__ import annotations

from pathlib import Path

import pytest

from core.context import Context
from core.registry import PluginRegistry
from core.plugin import Plugin
from plugins.core.config_validation import ConfigValidationPlugin
from plugins.core.formal_contracts import FormalContractsPlugin
from plugins.core.linting import LintingPlugin
from plugins.tools.file import FileTools


class PluginWithSchema(Plugin):
    name = "plugin_with_schema"
    __config_schema__ = {"required": ["api_key"]}


class PluginEmptySchema(Plugin):
    name = "plugin_empty_schema"
    __config_schema__ = {}


def test_config_validation_missing_required_key(tmp_path):
    ctx = Context(config={"workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register_class(LintingPlugin, root=tmp_path)
    reg.register_class(FormalContractsPlugin)
    reg.register_class(ConfigValidationPlugin)
    reg.register_class(PluginWithSchema)
    reg.start_all()
    cv = ctx.plugins["config_validation"]
    issues = cv.validate_plugin_config("plugin_with_schema", ctx.plugins["plugin_with_schema"], ctx.config)
    assert any("api_key" in str(i.key) for i in issues)


def test_config_validation_empty_schema():
    ctx = Context(config={})
    reg = PluginRegistry(ctx)
    reg.register_class(LintingPlugin, root=Path("."))
    reg.register_class(FormalContractsPlugin)
    reg.register_class(ConfigValidationPlugin)
    reg.register_class(PluginEmptySchema)
    reg.start_all()
    cv = ctx.plugins["config_validation"]
    issues = cv.validate_plugin_config("plugin_empty_schema", ctx.plugins["plugin_empty_schema"], ctx.config)
    assert issues == []


def test_config_validation_emits_event(tmp_path):
    ctx = Context(config={"workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register_class(LintingPlugin, root=tmp_path)
    reg.register_class(FormalContractsPlugin)
    reg.register_class(ConfigValidationPlugin)
    reg.register_class(PluginWithSchema)
    reg.start_all()
    cv = ctx.plugins["config_validation"]
    events = []
    def capture(event):
        events.append(event)
    ctx.events.on("config.violation", capture)
    cv.validate_all()
    assert any(e.payload.get("key") == "api_key" for e in events)
