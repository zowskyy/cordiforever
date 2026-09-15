from __future__ import annotations

import pytest

from core.fault_injection import FaultInjector
from core.errors import ToolError


def test_inject_timeout_raises_within_probability():
    injector = FaultInjector()
    with pytest.raises(ToolError, match="Simulated timeout"):
        injector.inject_timeout("file_read", probability=1.0)


def test_inject_malformed_args_raises_within_probability():
    injector = FaultInjector()
    with pytest.raises(ToolError, match="Simulated malformed args"):
        injector.inject_malformed_args("file_write", probability=1.0)


def test_inject_timeout_respects_probability():
    injector = FaultInjector()
    failures = 0
    for _ in range(100):
        try:
            injector.inject_timeout("file_read", probability=0.0)
        except ToolError:
            failures += 1
    assert failures == 0


class FakeContext:
    def __init__(self):
        self.messages = []
    def clear_messages(self):
        self.messages = []
    def append_message(self, role, content):
        self.messages.append({"role": role, "content": content})


def test_inject_stale_context_clears_messages():
    injector = FaultInjector()
    ctx = FakeContext()
    ctx.append_message("user", "hello")
    ctx.append_message("assistant", "world")
    injector.inject_stale_context(ctx, probability=1.0)
    assert len(ctx.messages) == 1
    assert ctx.messages[0]["content"] == "Context was reset due to stale state."


def test_inject_stale_context_respects_probability():
    injector = FaultInjector()
    ctx = FakeContext()
    ctx.append_message("user", "hello")
    injector.inject_stale_context(ctx, probability=0.0)
    assert len(ctx.messages) == 1
