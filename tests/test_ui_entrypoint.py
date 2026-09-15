from __future__ import annotations

import ui
from core.messages import Message
from plugins.model.ollama import OllamaModel


def test_ui_agent_uses_production_factory_settings(monkeypatch):
    seen = {}

    def fake_chat(self, messages, tools):
        seen["response_format"] = self.response_format
        seen["options"] = self.options
        seen["system"] = messages[0].content
        return Message("assistant", '{"tool": "done", "args": {"summary": "UI run finished."}}',
                       tool_calls=[{"function": {"name": "call_tool", "arguments": {"tool": "done", "args": {"summary": "UI run finished."}}}}])

    monkeypatch.setattr(OllamaModel, "chat", fake_chat)
    assert ui.run_agent("wrap up", model="gemma3:1b", ollama_url="http://127.0.0.1:9") == "UI run finished."
    assert seen["response_format"] is not None and "anyOf" in seen["response_format"]
    assert seen["options"] == {"temperature": 0.0, "num_predict": 2048}
    assert "You CAN read and change files" in seen["system"]


def test_ui_setup_failure_is_reported_not_raised(monkeypatch):
    def broken_factory(*args, **kwargs):
        raise RuntimeError("factory exploded")

    monkeypatch.setattr(ui, "build_application", broken_factory)
    assert ui.run_agent("anything") == "Error: factory exploded"
