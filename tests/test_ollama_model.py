from __future__ import annotations

import json
from typing import Any

import pytest

from core.calibration import preset_key_for_model, resolve_calibration
from core.errors import ModelError
from core.messages import Message
from plugins.model import ollama as ollama_module
from plugins.model.ollama import OllamaModel


class FakeResponse:
    def __init__(self, status_code: int = 200, body: Any = None, lines: list[dict[str, Any]] | None = None) -> None:
        self.status_code = status_code
        self._body = body
        self._lines = lines or []

    @property
    def text(self) -> str:
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    def json(self) -> Any:
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body

    def iter_lines(self, decode_unicode: bool = False):
        for line in self._lines:
            yield json.dumps(line)


class FakeOllama:
    def __init__(self, capabilities: list[str] | None, reject_tools: bool = False, show_fails: bool = False) -> None:
        self.capabilities = capabilities
        self.reject_tools = reject_tools
        self.show_fails = show_fails
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, json: dict[str, Any], timeout: float, stream: bool) -> FakeResponse:
        path = url.split("11434", 1)[1]
        self.calls.append((path, json))
        if path == "/api/show":
            if self.show_fails:
                return FakeResponse(404, {"error": "not found"})
            body = {} if self.capabilities is None else {"capabilities": self.capabilities}
            return FakeResponse(200, body)
        if path == "/api/chat":
            if "tools" in json and self.reject_tools:
                return FakeResponse(400, {"error": f"registry.ollama.ai/library/{json['model']} does not support tools"})
            reply = {"role": "assistant", "content": "done"}
            if json.get("stream"):
                return FakeResponse(200, lines=[{"message": reply, "done": True, "prompt_eval_count": 3, "eval_count": 1}])
            return FakeResponse(200, {"message": reply, "prompt_eval_count": 3, "eval_count": 1})
        raise AssertionError(f"unexpected path {path}")

    def chat_payloads(self) -> list[dict[str, Any]]:
        return [payload for path, payload in self.calls if path == "/api/chat"]


TOOLS = [{"type": "function", "function": {"name": "read_file", "description": "Read", "parameters": {"type": "object", "properties": {}}}}]
TOOL_CALLS = [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": {"path": "a.txt"}}}]
HISTORY = [
    Message(role="system", content="sys"),
    Message(role="user", content="read a.txt"),
    Message(role="assistant", content="", tool_calls=TOOL_CALLS),
    Message(role="tool", content="FILE-CONTENTS", tool_name="read_file"),
]


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeOllama) -> None:
    monkeypatch.setattr(ollama_module.requests, "post", fake.post)


def test_model_without_tool_capability_gets_tool_results_as_user_turns(monkeypatch):
    fake = FakeOllama(capabilities=["completion"])
    _install(monkeypatch, fake)
    model = OllamaModel(model="gemma3:1b")

    reply = model.chat(HISTORY, TOOLS)

    assert reply.content == "done"
    (payload,) = fake.chat_payloads()
    assert "tools" not in payload
    roles = [m["role"] for m in payload["messages"]]
    assert "tool" not in roles
    assert payload["messages"][2] == {"role": "assistant", "content": json.dumps({"tool_calls": TOOL_CALLS}, ensure_ascii=False)}
    assert payload["messages"][3] == {"role": "user", "content": "[tool result: read_file]\nFILE-CONTENTS"}


def test_capability_probe_is_cached_across_calls(monkeypatch):
    fake = FakeOllama(capabilities=["completion"])
    _install(monkeypatch, fake)
    model = OllamaModel(model="gemma3:1b")

    model.chat(HISTORY, TOOLS)
    model.chat(HISTORY, TOOLS)

    assert [path for path, _ in fake.calls].count("/api/show") == 1


def test_model_with_tool_capability_keeps_native_wire_format(monkeypatch):
    fake = FakeOllama(capabilities=["completion", "tools"])
    _install(monkeypatch, fake)
    model = OllamaModel(model="qwen2.5-coder:1.5b")

    model.chat(HISTORY, TOOLS)

    (payload,) = fake.chat_payloads()
    assert payload["tools"] == TOOLS
    assert payload["messages"] == [m.to_dict() for m in HISTORY]


def test_tools_rejection_falls_back_when_capabilities_unknown(monkeypatch):
    fake = FakeOllama(capabilities=None, reject_tools=True, show_fails=True)
    _install(monkeypatch, fake)
    model = OllamaModel(model="gemma3:1b")

    reply = model.chat(HISTORY, TOOLS)

    assert reply.content == "done"
    first, second = fake.chat_payloads()
    assert "tools" in first
    assert "tools" not in second
    assert second["messages"][3]["role"] == "user"
    assert model.supports_native_tools() is False


def test_http_error_body_is_surfaced(monkeypatch):
    fake = FakeOllama(capabilities=["completion", "tools"], reject_tools=True)
    _install(monkeypatch, fake)
    model = OllamaModel(model="qwen2.5-coder:1.5b")
    model._native_tools = True

    model.chat([Message(role="user", content="hi")], [])
    with pytest.raises(ModelError, match="HTTP 400.*does not support tools"):
        model._post("/api/chat", {"model": "x", "tools": TOOLS})


def test_stream_chat_translates_and_falls_back(monkeypatch):
    fake = FakeOllama(capabilities=None, reject_tools=True, show_fails=True)
    _install(monkeypatch, fake)
    model = OllamaModel(model="gemma3:1b")

    chunks = list(model.stream_chat(HISTORY, TOOLS))

    assert chunks[-1].content == "done"
    assert model.last_token_usage is not None
    first, second = fake.chat_payloads()
    assert first["stream"] is True and second["stream"] is True
    assert "tools" not in second
    assert all(m["role"] != "tool" for m in second["messages"])


def test_gemma_resolves_to_its_own_calibration_preset():
    assert preset_key_for_model("gemma3:1b") == "1b"
    cal = resolve_calibration("gemma3:1b")
    assert cal["preset"] == "1b"
    assert cal["max_tokens"] == 32768
    assert preset_key_for_model("qwen2.5-coder:1.5b") == "1.5b"
