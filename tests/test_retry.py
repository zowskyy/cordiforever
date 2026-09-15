from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from core.retry import RetryPolicy, _compute_delay, retry_with_backoff


def test_retry_policy_defaults():
    policy = RetryPolicy()
    assert policy.max_retries == 3
    assert policy.base_delay == 0.01
    assert policy.max_delay == 60.0
    assert policy.jitter == 0.0
    assert policy.backoff_formula == "exponential"


def test_compute_delay_exponential():
    policy = RetryPolicy(base_delay=1.0, jitter=0.0)
    assert _compute_delay(policy, 0) == 1.0
    assert _compute_delay(policy, 1) == 2.0
    assert _compute_delay(policy, 2) == 4.0


def test_compute_delay_caps_at_max():
    policy = RetryPolicy(base_delay=1.0, max_delay=3.0, jitter=0.0)
    assert _compute_delay(policy, 2) == 3.0


def test_compute_delay_linear():
    policy = RetryPolicy(base_delay=1.0, backoff_formula="linear", jitter=0.0)
    assert _compute_delay(policy, 0) == 1.0
    assert _compute_delay(policy, 1) == 2.0
    assert _compute_delay(policy, 2) == 3.0


def test_compute_delay_jitter():
    policy = RetryPolicy(base_delay=1.0, jitter=0.5)
    with patch("random.uniform", return_value=0.5):
        delay = _compute_delay(policy, 0)
    assert delay == 1.5


def test_retry_with_backoff_succeeds_first_try():
    call_count = 0

    def succeed():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = retry_with_backoff(succeed)
    assert result == "ok"
    assert call_count == 1


def test_retry_with_backoff_succeeds_on_retry():
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient")
        return "ok"

    with patch("time.sleep"):
        result = retry_with_backoff(flaky, policy=RetryPolicy(max_retries=3, base_delay=0.0))
    assert result == "ok"
    assert call_count == 3


def test_retry_with_backoff_exhausts_max_retries():
    call_count = 0

    def always_fail():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("always fails")

    with patch("time.sleep"):
        with pytest.raises(RuntimeError, match="always fails"):
            retry_with_backoff(always_fail, policy=RetryPolicy(max_retries=2, base_delay=0.0))
    assert call_count == 3  # 1 initial + 2 retries


def test_retry_with_backoff_non_retryable_fails_fast():
    call_count = 0

    def fail():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad args")

    with patch("time.sleep") as sleep_mock:
        with pytest.raises(ValueError, match="bad args"):
            retry_with_backoff(
                fail,
                policy=RetryPolicy(max_retries=3, base_delay=0.0),
                should_retry=lambda exc: isinstance(exc, RuntimeError),
            )
    assert call_count == 1
    sleep_mock.assert_not_called()


def test_retry_with_backoff_timing():
    delays = []

    def capture_delay(secs):
        delays.append(secs)

    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient")
        return "ok"

    with patch("time.sleep", side_effect=capture_delay):
        retry_with_backoff(flaky, policy=RetryPolicy(max_retries=3, base_delay=1.0, jitter=0.0))

    assert len(delays) == 2
    assert delays[0] == 1.0  # attempt 0 -> 1 * 2^0 = 1
    assert delays[1] == 2.0  # attempt 1 -> 1 * 2^1 = 2


def test_retry_with_backoff_preserves_exception():
    def fail():
        raise TypeError("type error")

    with patch("time.sleep"):
        with pytest.raises(TypeError, match="type error"):
            retry_with_backoff(fail, policy=RetryPolicy(max_retries=1, base_delay=0.0))


def test_agent_loop_retries_transient_tool_failure(tmp_path):
    from core.context import Context
    from core.errors import ToolError
    from core.messages import Message
    from core.plugin import Plugin
    from core.registry import PluginRegistry
    from plugins.agent.loop import AgentLoop
    from plugins.core.event_logger import EventLogger
    from plugins.tools.file import FileTools

    call_count = 0

    def flaky_write_file(path, content):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ToolError(f"timeout writing {path}")
        return f"Wrote {len(content)} bytes to {path}"

    class FakeModel(Plugin):
        name = "ollama_model"
        dependencies = ()

        def __init__(self):
            super().__init__()
            self.calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return Message("assistant", "", tool_calls=[
                    {"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}
                ])
            return Message("assistant", "done")

    ctx = Context(config={})
    reg = PluginRegistry(ctx)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(FakeModel())
    file_tools = FileTools(tmp_path)
    reg.register(file_tools)
    reg.register(AgentLoop())
    reg.start_all()

    with patch.object(file_tools, "write_file", side_effect=flaky_write_file):
        result = ctx.plugins["agent_loop"].run("create a file")

    assert result == "done"
    assert call_count == 3
    reg.stop_all()
