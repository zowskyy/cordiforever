from __future__ import annotations

import pytest
from core.session import SessionRegistry, get_session_registry


class FakeContext:
    pass


def test_session_registry_register_get():
    ctx = FakeContext()
    registry = get_session_registry(ctx)
    registry.register("tool", {"name": "file"})
    assert registry.get("tool") == {"name": "file"}
    assert registry.get("missing", "default") == "default"


def test_session_registry_unregister():
    ctx = FakeContext()
    registry = get_session_registry(ctx)
    registry.register("x", 1)
    registry.unregister("x")
    assert registry.get("x") is None


def test_get_session_registry_returns_same_instance():
    ctx = FakeContext()
    r1 = get_session_registry(ctx)
    r2 = get_session_registry(ctx)
    assert r1 is r2
