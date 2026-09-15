"""Measure full profile token costs."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.context import Context
from core.registry import PluginRegistry
from core.messages import Message
from core.metrics import TokenUsage
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools


class RecordingModel(OllamaModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []
    
    def chat(self, messages, tools):
        response = super().chat(messages, tools)
        usage = self.last_token_usage or TokenUsage()
        self.calls.append({
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "prompt_eval_count": usage.prompt_eval_count,
            "eval_count": usage.eval_count,
            "messages_count": len(messages),
            "tools_count": len(tools),
        })
        return response


def measure_task(task_name, user_input, profile="lite"):
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        ctx = Context(config={
            "workspace": str(workspace),
            "model": "qwen2.5-coder:1.5b",
            "profile": profile,
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
        model = RecordingModel(model="qwen2.5-coder:1.5b")
        files = FileTools(workspace)
        reg.register(EventLogger(workspace / "test.db"))
        reg.register(model)
        reg.register(files)
        reg.register(AgentLoop(max_rounds=5))
        reg.start_all()
        
        try:
            result = ctx.plugins["agent_loop"].run(user_input)
        finally:
            reg.stop_all()
        
        total_input = sum(c["input_tokens"] for c in model.calls)
        total_output = sum(c["output_tokens"] for c in model.calls)
        total_prompt = sum(c["prompt_eval_count"] for c in model.calls)
        total_eval = sum(c["eval_count"] for c in model.calls)
        
        print(f"\n=== {task_name} ({profile}) ===")
        print(f"Model calls: {len(model.calls)}")
        for i, c in enumerate(model.calls):
            print(f"  Call {i+1}: prompt={c['prompt_eval_count']}, eval={c['eval_count']}, msgs={c['messages_count']}, tools={c['tools_count']}")
        print(f"Total prompt tokens: {total_prompt}")
        print(f"Total output tokens: {total_eval}")
        print(f"Total tokens: {total_prompt + total_eval}")
        print(f"Result: {str(result)[:100]}")


if __name__ == "__main__":
    # Compare lite vs full for tasks that reach the model
    measure_task("complex_task_lite", "calculate the derivative of x^2 + 3x", "lite")
    measure_task("complex_task_full", "calculate the derivative of x^2 + 3x", "full")
    measure_task("simple_chat_lite", "say hello", "lite")
    measure_task("simple_chat_full", "say hello", "full")
