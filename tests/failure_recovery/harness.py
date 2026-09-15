from __future__ import annotations

import json
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.context import Context
from core.errors import ToolError
from core.event_log import EventLog
from core.fault_injection import FaultInjector
from core.messages import Message
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.tools.file import FileTools


@dataclass
class Task:
    name: str
    user_input: str
    model_responses: list[Message]
    expected_output: str
    fault_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    total_steps: int = 0
    optional_steps: int = 0


@dataclass
class Scorecard:
    task_name: str
    seed: int
    policy: str
    task_success: bool = False
    invalid_call_rate: float = 0.0
    recovery_rate: float = 0.0
    silent_failure_rate: float = 0.0
    loop_rate: float = 0.0
    steps_used: int = 0
    retries_used: int = 0
    replans_used: int = 0
    tool_calls_used: int = 0
    budget_exhausted: bool = False
    error: str | None = None
    partial_completion: float = 0.0
    efficiency: float = 0.0
    failure_attribution: dict[str, int] = field(default_factory=dict)
    recovery_latency: int = 0
    cascade_rate: float = 0.0
    total_steps: int = 0
    optional_steps: int = 0


class FaultInjectingModel(Plugin):
    name = "ollama_model"

    def __init__(self, responses, fault_config=None):
        super().__init__()
        self.responses = list(responses)
        self.fault_config = fault_config or {}
        self.call_count = 0

    def chat(self, messages, tools):
        self.call_count += 1
        if self.call_count in self.fault_config.get("model_errors", []):
            raise ToolError(f"Simulated model error at call {self.call_count}")
        if self.call_count in self.fault_config.get("malformed_responses", []):
            return Message("assistant", "This is not a valid JSON tool call")
        return self.responses.pop(0) if self.responses else Message("assistant", "No more responses")


class FaultInjectingTools(FileTools):
    def __init__(self, *args, fault_config=None, wrong_outputs=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fault_config = fault_config or {}
        self.wrong_outputs = wrong_outputs or {}
        self.injector = FaultInjector()
        self.call_counts: dict[str, int] = {}

    def _inject(self, name):
        key = f"{name}:{self._last_path}"
        self.call_counts[key] = self.call_counts.get(key, 0) + 1
        self.injector.inject_timeout(name, self.fault_config.get(f"{name}_timeout", 0.0))
        self.injector.inject_malformed_args(name, self.fault_config.get(f"{name}_malformed", 0.0))

    def read_file(self, path: str) -> str:
        self._last_path = path
        self._inject("read_file")
        if f"read_file:{path}" in self.wrong_outputs:
            return self.wrong_outputs[f"read_file:{path}"]
        return super().read_file(path)

    def write_file(self, path: str, content: str) -> str:
        self._last_path = path
        self._inject("write_file")
        return super().write_file(path, content)

    def list_directory(self, path: str = ".") -> list[str]:
        self._last_path = path
        self._inject("list_directory")
        if f"list_directory:{path}" in self.wrong_outputs:
            return self.wrong_outputs[f"list_directory:{path}"]
        return super().list_directory(path)


class DeterministicSandbox:
    def __init__(self, seed=42, tmp_path=None):
        self.seed = seed
        self.tmp_path = tmp_path or Path(tempfile.mkdtemp())

    def run_task(self, task, policy="retry"):
        db_path = self.tmp_path / f"{self.seed}_{task.name}_{policy}.db"
        workspace = self.tmp_path / f"{self.seed}_{task.name}_{policy}_ws"
        ctx, reg = _make_registry(self.tmp_path, task.model_responses, task.fault_config, max_rounds=max(20, len(task.model_responses)), db_path=db_path, workspace=workspace)
        sc = Scorecard(task_name=task.name, seed=self.seed, policy=policy, total_steps=task.total_steps)
        try:
            result = ctx.plugins["agent_loop"].run(task.user_input)
            sc.task_success = result == task.expected_output
            sc.steps_used = len(ctx.messages)
            sc.tool_calls_used = sum(1 for m in ctx.messages if m.tool_calls)
            el = ctx.plugins["event_logger"]
            events = el.event_log.get_session_events(el.continuity.session_id)
            sc = _metrics(events, sc)
        except Exception as exc:
            sc.error = str(exc)
        finally:
            reg.stop_all()
            ctx.plugins["event_logger"].event_log.close()
        return sc


def _make_registry(tmp_path, responses, fault_config=None, max_rounds=5, db_path=None, workspace=None):
    ctx = Context()
    reg = PluginRegistry(ctx)
    tf = {k: v for k, v in (fault_config or {}).items() if k.endswith("_timeout") or k.endswith("_malformed")}
    wo = (fault_config or {}).get("wrong_outputs", {})
    reg.register(EventLogger(db_path or tmp_path / "test.db"))
    reg.register(FaultInjectingModel(responses, fault_config))
    reg.register(FaultInjectingTools(workspace or tmp_path, fault_config=tf, wrong_outputs=wo))
    reg.register(AgentLoop(max_rounds=max_rounds))
    reg.start_all()
    return ctx, reg


def _payload(event):
    raw = event.payload
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _metrics(events, sc):
    invocations = [e for e in events if e.type == "tool.invoked"]
    results = [e for e in events if e.type == "tool.result"]
    sc.invalid_call_rate = sum(1 for e in results if not _payload(e).get("success", True) and "Unknown tool" in str(_payload(e).get("error", ""))) / max(len(invocations), 1)

    recovered = failures = 0
    failed: dict[str, bool] = {}
    for e in results:
        p = _payload(e)
        if "success" not in p:
            continue
        name = p.get("tool_name") or p.get("tool", "")
        if not p.get("success", True):
            failed[name] = True
            failures += 1
        elif name in failed:
            recovered += 1
            failed[name] = False
    sc.recovery_rate = recovered / max(failures, 1) if failures > 0 else 1.0
    sc.silent_failure_rate = sum(1 for e in results if _payload(e).get("success") and _payload(e).get("silent_wrong")) / max(len(results), 1)

    counts = {}
    for e in events:
        if e.type == "tool.invoked":
            sig = (e.payload.get("tool_name"), json.dumps(e.payload.get("arguments", {}), sort_keys=True))
            counts[sig] = counts.get(sig, 0) + 1
    sc.loop_rate = sum(1 for c in counts.values() if c >= 3) / max(len(invocations), 1)

    if sc.total_steps > 0:
        invocations = [e for e in events if e.type == "tool.invoked"]
        sc.partial_completion = min(1.0, len(invocations) / sc.total_steps)
        if len(invocations) > 0:
            sc.efficiency = sum(1 for e in results if _payload(e).get("success", False)) / len(invocations)

    attribution: dict[str, int] = {}
    for e in results:
        p = _payload(e)
        if not p.get("success", True):
            name = p.get("tool_name") or p.get("tool", "unknown")
            attribution[name] = attribution.get(name, 0) + 1
    sc.failure_attribution = attribution

    recovery_steps = []
    for i, e in enumerate(results):
        p = _payload(e)
        if not p.get("success", True):
            for j in range(i + 1, len(results)):
                p2 = _payload(results[j])
                if p2.get("success", False):
                    recovery_steps.append(j - i)
                    break
    sc.recovery_latency = sum(recovery_steps) / len(recovery_steps) if recovery_steps else 0

    cascade = 0
    for i, e in enumerate(results):
        if not _payload(e).get("success", True):
            for j in range(i + 1, min(i + 4, len(results))):
                if not _payload(results[j]).get("success", True):
                    cascade += 1
                    break
    sc.cascade_rate = cascade / max(len([e for e in results if not _payload(e).get("success", True)]), 1) if any(not _payload(e).get("success", True) for e in results) else 0.0
    return sc


def summarize(scorecards):
    if not scorecards:
        return {}
    phase3 = [s for s in scorecards if s.total_steps > 0]
    return {
        "tasks": len(scorecards),
        "success_rate": sum(1 for s in scorecards if s.task_success) / len(scorecards),
        "avg_invalid_call_rate": sum(s.invalid_call_rate for s in scorecards) / len(scorecards),
        "avg_recovery_rate": sum(s.recovery_rate for s in scorecards) / len(scorecards),
        "avg_silent_failure_rate": sum(s.silent_failure_rate for s in scorecards) / len(scorecards),
        "avg_loop_rate": sum(s.loop_rate for s in scorecards) / len(scorecards),
        "avg_steps": sum(s.steps_used for s in scorecards) / len(scorecards),
        "avg_tool_calls": sum(s.tool_calls_used for s in scorecards) / len(scorecards),
        "budget_exhausted_count": sum(1 for s in scorecards if s.budget_exhausted),
        "avg_partial_completion": sum(s.partial_completion for s in phase3) / len(phase3) if phase3 else 0.0,
        "avg_efficiency": sum(s.efficiency for s in phase3) / len(phase3) if phase3 else 0.0,
        "avg_recovery_latency": sum(s.recovery_latency for s in phase3) / len(phase3) if phase3 else 0.0,
        "avg_cascade_rate": sum(s.cascade_rate for s in phase3) / len(phase3) if phase3 else 0.0,
    }
