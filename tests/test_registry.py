import pytest

from core.context import Context
from core.errors import PluginError
from core.plugin import Plugin
from core.registry import PluginRegistry


class A(Plugin):
    name = "a"


class B(Plugin):
    name = "b"
    dependencies = ("a",)


class C(Plugin):
    name = "c"
    dependencies = ("missing",)


def test_register_plugin_sets_context():
    ctx = Context()
    registry = PluginRegistry(ctx)
    plugin = A()
    registry.register(plugin)
    assert plugin.context is ctx
    assert ctx.plugins["a"] is plugin


def test_register_rejects_duplicate():
    registry = PluginRegistry(Context())
    registry.register(A())
    with pytest.raises(PluginError):
        registry.register(A())


def test_register_rejects_missing_dependencies():
    registry = PluginRegistry(Context())
    with pytest.raises(PluginError):
        registry.register(C())


def test_stop_all_reverses_order():
    events = []

    class X(Plugin):
        name = "x"
        def stop(self):
            events.append("x")

    class Y(Plugin):
        name = "y"
        dependencies = ("x",)
        def stop(self):
            events.append("y")

    registry = PluginRegistry(Context())
    registry.register(X())
    registry.register(Y())
    registry.stop_all()
    assert events == ["y", "x"]


def test_unregister_removes_plugin():
    registry = PluginRegistry(Context())
    registry.register(A())
    registry.unregister("a")
    assert "a" not in registry.names()
    assert "a" not in registry.context.plugins
