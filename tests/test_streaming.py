from __future__ import annotations

import json
from pathlib import Path

from core.context import Context
from core.messages import Message
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools


class FakeStreamModel(Plugin):
    name = "ollama_model"
    dependencies = ()

    def __init__(self, chunks):
        super().__init__()
        self.chunks = chunks

    def chat(self, messages, tools):
        return Message("assistant", "done")

    def stream_chat(self, messages, tools):
        for chunk in self.chunks:
            yield chunk

    def start(self):
        pass

    def stop(self):
        pass


def test_agent_loop_streaming(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    chunks = [
        Message("assistant", "Hello"),
        Message("assistant", "Hello world"),
        Message("assistant", "Hello world!"),
    ]
    model = FakeStreamModel(chunks)
    files = FileTools(tmp_path)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3, stream=True))
    reg.start_all()

    received = []
    def on_stream(chunk):
        received.append(chunk.content)

    try:
        result = ctx.plugins["agent_loop"].run("hi", on_stream=on_stream)
        assert result == "Hello world!"
        assert received == ["Hello", "Hello world", "Hello world!"]
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()


def test_agent_loop_streaming_with_tool_calls(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    tool_call = {"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}
    chunks = [
        Message("assistant", "", tool_calls=[tool_call]),
        Message("assistant", "done"),
    ]
    model = FakeStreamModel(chunks)
    files = FileTools(tmp_path)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3, stream=True))
    reg.start_all()

    received = []
    def on_stream(chunk):
        received.append(chunk.content)

    try:
        result = ctx.plugins["agent_loop"].run("write file", on_stream=on_stream)
        assert result == "done"
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()


def test_agent_loop_non_streaming(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FakeStreamModel([])
    files = FileTools(tmp_path)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3, stream=False))
    reg.start_all()

    received = []
    def on_stream(chunk):
        received.append(chunk.content)

    try:
        result = ctx.plugins["agent_loop"].run("hi", on_stream=on_stream)
        assert result == "done"
        assert received == []
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()
