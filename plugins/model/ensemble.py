from __future__ import annotations

import json
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterator, Optional

from core.errors import ModelError
from core.messages import Message
from core.plugin import Plugin
from plugins.model.ollama import OllamaModel


class EnsembleModel(Plugin):
    name = "ensemble_model"

    def __init__(
        self,
        models: Optional[list[dict[str, Any]]] = None,
        strategy: str = "parallel_vote",
        max_workers: int = 3,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self.strategy = strategy
        self.max_workers = max_workers
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._members: list[OllamaModel] = []
        self._router = EnsembleRouter()

        model_names = []
        if models:
            for cfg in models:
                name = cfg.get("model")
                if name:
                    model_names.append(name)
                    self._members.append(OllamaModel(model=name, base_url=base_url, timeout=timeout))

        if not self._members:
            model_names = ["qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b"]
            for name in model_names:
                self._members.append(OllamaModel(model=name, base_url=base_url, timeout=timeout))

        self.model_names = model_names

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        routing = self._router.route(messages, tools)
        mode = routing.get("mode", "delegate")

        if mode == "delegate":
            model_name = routing.get("model", self.model_names[0])
            consult_group = routing.get("consult_group_if_needed", False)
            primary = self._get_model_by_name(model_name)
            if primary is None:
                primary = self._members[0]
            try:
                return primary.chat(messages, tools)
            except Exception:
                if consult_group and len(self._members) > 1:
                    return self._parallel_vote(messages, tools)
                raise
        if mode == "gather_consensus":
            return self._parallel_vote(messages, tools)
        raise ModelError(f"Unknown routing mode: {mode}")

    def _get_model_by_name(self, name: str) -> Optional[OllamaModel]:
        for model in self._members:
            if model.model == name:
                return model
        return None

    def stream_chat(self, messages: list[Message], tools: list[dict[str, Any]]) -> Iterator[Message]:
        response = self.chat(messages, tools)
        yield response

    def _parallel_vote(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        candidates = self._run_parallel(messages, tools)
        if len(candidates) == 1:
            return candidates[0]

        return self._aggregate(candidates, messages, tools)

    def _chairman(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        candidates = self._run_parallel(messages, tools)
        return self._synthesize(candidates, messages, tools)

    def _fastest(self, messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        import time
        best = None
        best_time = None
        for model in self._members:
            start = time.time()
            try:
                resp = model.chat(messages, tools)
                elapsed = time.time() - start
                if best is None or elapsed < best_time:
                    best = resp
                    best_time = elapsed
            except Exception:
                continue
        if best is None:
            raise ModelError("All ensemble members failed.")
        return best

    def _run_parallel(self, messages: list[Message], tools: list[dict[str, Any]]) -> list[Message]:
        candidates: list[Optional[Message]] = [None] * len(self._members)
        errors: list[Optional[Exception]] = [None] * len(self._members)

        def _call(model_idx: int, model: OllamaModel) -> None:
            try:
                candidates[model_idx] = model.chat(messages, tools)
            except Exception as exc:
                errors[model_idx] = exc

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(_call, i, m) for i, m in enumerate(self._members)]
            for future in as_completed(futures):
                future.result()

        return [c for c in candidates if c is not None] or [Message("assistant", "Ensemble failed.")]

    def _aggregate(self, candidates: list[Message], messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        tool_names = [t.get("function", {}).get("name", "") for t in tools if isinstance(t, dict)]

        parsed_calls: list[tuple[str, dict[str, Any], Message]] = []
        for msg in candidates:
            calls = msg.tool_calls or []
            if calls:
                for call in calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    if name in tool_names:
                        parsed_calls.append((name, fn.get("arguments") or {}, msg))

        if parsed_calls:
            best = self._vote(parsed_calls)
            if best:
                return Message(
                    role="assistant",
                    content="",
                    tool_calls=[{
                        "id": f"call_{random.randint(10000000, 99999999):08x}",
                        "type": "function",
                        "function": {
                            "name": best[0],
                            "arguments": best[1],
                        }
                    }]
                )

        contents = [msg.content.strip() for msg in candidates if msg.content and msg.content.strip()]
        if not contents:
            return Message("assistant", "No answer.")
        return Message("assistant", contents[0])

    def _synthesize(self, candidates: list[Message], messages: list[Message], tools: list[dict[str, Any]]) -> Message:
        return self._aggregate(candidates, messages, tools)

    def _vote(self, parsed_calls: list[tuple[str, dict[str, Any], Message]]) -> Optional[tuple[str, dict[str, Any]]]:
        if not parsed_calls:
            return None

        groups: dict[str, list[dict[str, Any]]] = {}
        for name, args, _ in parsed_calls:
            key = json.dumps(args, sort_keys=True, ensure_ascii=False)
            groups.setdefault(name, [])
            groups[name].append(key)

        best_name = None
        best_args_str = None
        best_count = -1
        for name, key_list in groups.items():
            counts: dict[str, int] = {}
            for key in key_list:
                counts[key] = counts.get(key, 0) + 1
                if counts[key] > best_count:
                    best_count = counts[key]
                    best_name = name
                    best_args_str = key

        if best_name is not None:
            return best_name, json.loads(best_args_str)
        return parsed_calls[0][0], parsed_calls[0][1]


class EnsembleRouter:
    def route(self, messages: list[Message], tools: list[dict[str, Any]]) -> dict:
        user_text = " ".join(m.content.lower() for m in messages if m.role == "user")
        tool_names = [t.get("function", {}).get("name", "") for t in tools]
        complexity = self._estimate_complexity(user_text, tool_names)

        if complexity == "low":
            peer = self._consult_specialist(user_text, tool_names)
            return {"mode": "delegate", "model": peer, "consult_group_if_needed": True}
        if complexity == "medium":
            peer = self._consult_peer(user_text, tool_names)
            return {"mode": "delegate", "model": peer, "consult_group_if_needed": True}
        return {"mode": "gather_consensus", "models": self._gather_consensus(user_text, tool_names)}

    def _estimate_complexity(self, user_text: str, tool_names: list[str]) -> str:
        if len(tool_names) <= 2 and len(user_text.split()) < 15:
            return "low"
        if any(k in user_text for k in ["refactor", "debug", "fix", "test", "pytest"]):
            return "high"
        return "medium"

    def _consult_specialist(self, user_text: str, tool_names: list[str]) -> str:
        if any(k in user_text for k in ["math", "calculate", "compute"]):
            return "qwen2.5-coder:1.5b"
        if any(k in user_text for k in ["file", "read", "write", "list"]):
            return "qwen2.5-coder:1.5b"
        return "qwen2.5-coder:1.5b"

    def _consult_peer(self, user_text: str, tool_names: list[str]) -> str:
        if any(k in user_text for k in ["code", "refactor", "function", "class", "debug", "fix"]):
            return "my-ai-stack/Stack-2-9-finetuned"
        if any(k in user_text for k in ["file", "read", "write", "list", "directory"]):
            return "delimitter/qwen2.5-1.5b-synoema-tools-v1"
        if any(k in user_text for k in ["test", "pytest", "run", "execute"]):
            return "my-ai-stack/Stack-2-9-finetuned"
        return "qwen2.5-coder:1.5b"

    def _gather_consensus(self, user_text: str, tool_names: list[str]) -> list[str]:
        if any(k in user_text for k in ["code", "refactor", "function", "class", "debug", "fix"]):
            return ["my-ai-stack/Stack-2-9-finetuned", "qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b"]
        if any(k in user_text for k in ["file", "read", "write", "list", "directory"]):
            return ["qwen2.5-coder:1.5b", "delimitter/qwen2.5-1.5b-synoema-tools-v1", "my-ai-stack/Stack-2-9-finetuned"]
        return ["qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b", "qwen2.5-coder:1.5b"]
