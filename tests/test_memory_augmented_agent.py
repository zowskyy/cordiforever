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
from plugins.ui.terminal import TerminalUI


class FakeModel(Plugin):
    name = "ollama_model"
    dependencies = ()

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.call_count = 0

    def chat(self, messages, tools):
        self.call_count += 1
        return self.responses.pop(0) if self.responses else Message("assistant", "done")


class FakeContextBuilder(Plugin):
    name = "context_builder"
    dependencies = ()

    def __init__(self, memory_context=""):
        super().__init__()
        self.memory_context = memory_context
        self.build_calls = []

    def build(self, session_id, query="", max_messages=50):
        self.build_calls.append({"session_id": session_id, "query": query})
        return {"messages": [], "summary": "No previous activity", "memory": self.memory_context, "reality": {}, "route": None}


def test_agent_loop_without_context_builder(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FakeModel([Message("assistant", "", tool_calls=[{"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}]), Message("assistant", "done")])
    files = FileTools(tmp_path)
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()
    try:
        result = ctx.plugins["agent_loop"].run("create a file")
        assert result == "done"
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()


def test_agent_loop_with_context_builder_augments_messages(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FakeModel([Message("assistant", "", tool_calls=[{"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}]), Message("assistant", "done")])
    files = FileTools(tmp_path)
    cb = FakeContextBuilder(memory_context="Known facts:\n- user likes Python")
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3))
    reg.register(TerminalUI())
    reg.start_all()
    ctx.plugins["context_builder"] = cb
    try:
        result = ctx.plugins["agent_loop"].run("create a file")
        assert result == "done"
        assert len(cb.build_calls) >= 1
        assert cb.build_calls[0]["query"] == "create a file"
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()


def test_agent_loop_emits_memory_augmented_event(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FakeModel([Message("assistant", "", tool_calls=[{"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}]), Message("assistant", "done")])
    files = FileTools(tmp_path)
    cb = FakeContextBuilder(memory_context="Known facts:\n- user likes Python")
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3))
    reg.register(TerminalUI())
    reg.start_all()
    ctx.plugins["context_builder"] = cb
    try:
        ctx.plugins["agent_loop"].run("create a file")
        el = ctx.plugins["event_logger"]
        cont = el.continuity
        session_id = cont.session_id if hasattr(cont, "session_id") else "default"
        events = el.event_log.get_session_events(session_id)
        memory_events = [e for e in events if e.type == "memory.augmented"]
        assert len(memory_events) >= 1
        assert memory_events[0].payload["context_length"] > 0
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()


def test_agent_loop_with_empty_memory_context(tmp_path):
    ctx = Context()
    reg = PluginRegistry(ctx)
    model = FakeModel([Message("assistant", "", tool_calls=[{"function": {"name": "write_file", "arguments": {"path": "a.txt", "content": "hello"}}}]), Message("assistant", "done")])
    files = FileTools(tmp_path)
    cb = FakeContextBuilder(memory_context="")
    reg.register(EventLogger(tmp_path / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=3))
    reg.register(TerminalUI())
    reg.start_all()
    ctx.plugins["context_builder"] = cb
    try:
        result = ctx.plugins["agent_loop"].run("create a file")
        assert result == "done"
        assert len(cb.build_calls) >= 1
    finally:
        reg.stop_all()
        ctx.plugins["event_logger"].event_log.close()
