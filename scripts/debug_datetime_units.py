"""Debug datetime and units tasks in full profile."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context
from core.registry import PluginRegistry
from core.messages import Message
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools


class DebugModel(OllamaModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def chat(self, messages, tools):
        response = super().chat(messages, tools)
        usage = self.last_token_usage or type('obj', (object,), {'input_tokens': 0, 'output_tokens': 0})()
        self.calls.append({
            "prompt_eval_count": getattr(usage, 'prompt_eval_count', 0),
            "eval_count": getattr(usage, 'eval_count', 0),
            "messages_count": len(messages),
            "tools_count": len(tools),
            "response_content": str(response.content)[:200],
            "response_tool_calls": response.tool_calls,
        })
        return response


with tempfile.TemporaryDirectory() as tmp:
    workspace = Path(tmp)
    ctx = Context(config={
        "workspace": str(workspace),
        "model": "qwen2.5-coder:1.5b",
        "profile": "full",
        "calibration": {
            "max_tokens": 32768,
            "pruner_budget": 30000,
            "safety": 0.85,
            "max_messages": 200,
            "rounds_per_file": 1.05,
            "max_tool_result_bytes": 65536,
        }
    })
    reg = PluginRegistry(ctx)
    model = DebugModel(model="qwen2.5-coder:1.5b")
    files = FileTools(workspace)
    reg.register(EventLogger(workspace / "test.db"))
    reg.register(model)
    reg.register(files)
    reg.register(AgentLoop(max_rounds=5))
    reg.start_all()

    for task in ["what is 3 days from now", "convert 100 km to miles"]:
        print(f"\n=== {task} ===")
        model.calls.clear()
        try:
            result = ctx.plugins["agent_loop"].run(task)
            print(f"Result: {str(result)[:100]}")
        except Exception as e:
            print(f"Error: {e}")
        print(f"Model calls: {len(model.calls)}")
        for i, c in enumerate(model.calls):
            print(f"  Call {i+1}: prompt={c['prompt_eval_count']}, eval={c['eval_count']}, msgs={c['messages_count']}, tools={c['tools_count']}")
            print(f"    Content: {c['response_content']}")
            print(f"    Tool calls: {c['response_tool_calls']}")

    reg.stop_all()
