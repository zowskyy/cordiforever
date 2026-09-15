"""Debug what context the model sees in full profile."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

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
        print(f"\n=== MODEL CALL ===")
        print(f"Messages ({len(messages)}):")
        for i, m in enumerate(messages):
            print(f"  [{i}] role={m.role}, content={str(m.content)[:100]}, tool_calls={m.tool_calls is not None}")
        print(f"Tools ({len(tools)}): {[t.get('function', {}).get('name') for t in tools]}")
        
        response = super().chat(messages, tools)
        usage = self.last_token_usage or type('obj', (object,), {'input_tokens': 0, 'output_tokens': 0})()
        self.calls.append({
            "prompt_eval_count": getattr(usage, 'prompt_eval_count', 0),
            "eval_count": getattr(usage, 'eval_count', 0),
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
    reg.register(AgentLoop(max_rounds=3))
    reg.start_all()

    print("=== what is 3 days from now ===")
    try:
        result = ctx.plugins["agent_loop"].run("what is 3 days from now")
        print(f"Result: {str(result)[:100]}")
    except Exception as e:
        print(f"Error: {e}")

    reg.stop_all()
