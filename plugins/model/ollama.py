from __future__ import annotations

import json
from typing import Any, Iterator, Optional

import requests

from core.errors import ModelError
from core.messages import Message
from core.metrics import TokenUsage
from core.plugin import Plugin
from core.tool_call_extraction import extract_tool_calls_from_text


class OllamaModel(Plugin):
    name = "ollama_model"

    def __init__(
        self,
        model: str = "gemma3:1b",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
        options: dict[str, Any] | None = None,
        response_format: dict[str, Any] | str | None = None,
        text_tool_protocol: bool = False,
    ) -> None:
        super().__init__()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.options = dict(options) if options else None
        self.response_format = response_format
        self.last_token_usage: TokenUsage | None = None
        self.last_done_reason: str | None = None
        # text_tool_protocol forces the text JSON action interface even for models with native tool support,
        # so model comparisons can hold the action interface constant.
        self._native_tools: bool | None = False if text_tool_protocol else None

    def _post(self, path: str, payload: dict[str, Any], stream: bool = False) -> Any:
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
                stream=stream,
            )
        except Exception as exc:
            raise ModelError(f"Could not reach Ollama at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            # The body carries Ollama's reason (e.g. "does not support tools"); raise_for_status() drops it.
            raise ModelError(
                f"Ollama at {self.base_url} returned HTTP {response.status_code} for {path}: {response.text[:1000]}"
            )
        return response

    def supports_native_tools(self) -> bool:
        if self._native_tools is None:
            try:
                caps = self._post("/api/show", {"model": self.model}).json().get("capabilities")
            except (ModelError, ValueError, AttributeError):
                return True
            self._native_tools = ("tools" in caps) if isinstance(caps, list) else True
        return self._native_tools

    @staticmethod
    def _wire_messages(messages: list[Message], native_tools: bool) -> list[dict[str, Any]]:
        if native_tools:
            return [message.to_dict() for message in messages]
        # Templates without tool support (e.g. gemma3) silently drop role="tool" and ignore tool_calls.
        wire: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                label = message.tool_name or message.name or "tool"
                wire.append({"role": "user", "content": f"[tool result: {label}]\n{message.content}"})
            elif message.role == "assistant" and message.tool_calls and not (message.content or "").strip():
                wire.append({"role": "assistant", "content": json.dumps({"tool_calls": message.tool_calls}, ensure_ascii=False)})
            else:
                wire.append({"role": message.role, "content": message.content})
        return wire

    def _chat_payload(self, messages: list[Message], tools: list[dict[str, Any]]) -> dict[str, Any]:
        native = self.supports_native_tools()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._wire_messages(messages, native),
        }
        if tools and native:
            payload["tools"] = tools
        if self.options:
            payload["options"] = dict(self.options)
        # Constrain only tool-bearing turns so auxiliary plain-text calls stay free-form.
        if self.response_format is not None and tools:
            payload["format"] = self.response_format
        return payload

    def _post_chat(self, messages: list[Message], tools: list[dict[str, Any]], stream: bool) -> Any:
        payload = self._chat_payload(messages, tools)
        payload["stream"] = stream
        try:
            return self._post("/api/chat", payload, stream=stream)
        except ModelError as exc:
            if "tools" in payload and "does not support tools" in str(exc):
                self._native_tools = False
                payload = self._chat_payload(messages, tools)
                payload["stream"] = stream
                return self._post("/api/chat", payload, stream=stream)
            raise

    @staticmethod
    def _iter_json_lines(response: Any) -> Iterator[dict[str, Any]]:
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def _extract_token_usage(self, data: dict[str, Any]) -> TokenUsage:
        prompt_eval_count = data.get("prompt_eval_count") or 0
        eval_count = data.get("eval_count") or 0
        return TokenUsage(
            prompt_eval_count=prompt_eval_count,
            eval_count=eval_count,
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> Message:
        response = self._post_chat(messages, tools, stream=False)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ModelError(f"Invalid JSON from Ollama: {response.text[:1000]}") from exc

        self.last_token_usage = self._extract_token_usage(data)
        self.last_done_reason = data.get("done_reason")

        raw_message = data.get("message")
        if not isinstance(raw_message, dict):
            raise ModelError("Ollama response did not contain a message object.")

        content = raw_message.get("content", "")
        tool_calls = raw_message.get("tool_calls")
        if not tool_calls and content:
            tool_calls = extract_tool_calls_from_text(content, tools)

        return Message(
            role=raw_message.get("role", "assistant"),
            content=content,
            tool_calls=tool_calls or None,
        )

    def stream_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ) -> Iterator[Message]:
        current_role: Optional[str] = None
        current_content = ""
        current_tool_calls: list[dict[str, Any]] = []
        last_data: dict[str, Any] = {}

        self.last_done_reason = None
        response = self._post_chat(messages, tools, stream=True)
        for chunk in self._iter_json_lines(response):
            message = chunk.get("message", {})
            role = message.get("role")
            content_delta = message.get("content", "")
            tool_calls_delta = message.get("tool_calls")

            if role:
                current_role = role
            if content_delta:
                current_content += content_delta
            if tool_calls_delta:
                current_tool_calls.extend(tool_calls_delta)

            last_data = chunk

            yield Message(
                role=current_role or "assistant",
                content=current_content,
                tool_calls=current_tool_calls if current_tool_calls else None,
            )

            if chunk.get("done"):
                break

        if last_data:
            self.last_token_usage = self._extract_token_usage(last_data)
            self.last_done_reason = last_data.get("done_reason")

    def list_models(self) -> list[str]:
        response = self._post("/api/tags", {})
        data = response.json()
        models = data.get("models", [])
        return [
            str(item["name"])
            for item in models
            if isinstance(item, dict) and "name" in item
        ]

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "healthy": True,
            "model": self.model,
            "base_url": self.base_url,
        }

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "prompt": text}
        response = self._post("/api/embeddings", payload)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ModelError(f"Invalid JSON from Ollama embeddings: {response.text[:1000]}") from exc
        embedding = data.get("embedding")
        if not isinstance(embedding, list):
            raise ModelError("Ollama embeddings response did not contain an embedding list.")
        return embedding
