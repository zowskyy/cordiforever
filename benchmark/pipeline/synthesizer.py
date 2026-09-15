from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.context import Context
from core.messages import Message
from core.registry import PluginRegistry
from plugins.agent.loop import AgentLoop
from plugins.core.event_logger import EventLogger
from plugins.model.ollama import OllamaModel
from plugins.tools.file import FileTools
from benchmark.tasks.integration import TaskRegistry
from benchmark.tasks.verification import KNOWN_TOOLS, TaskVerifier, VerifiedBenchmarkTask
from benchmark.pipeline.task_generator import GeneratedTask


class Trajectory:
    def __init__(self, task: GeneratedTask, conversation: List[Dict[str, Any]], result: str, success: bool, verification: Optional[Dict[str, Any]] = None) -> None:
        self.task = task
        self.conversation = conversation
        self.result = result
        self.success = success
        self.verification = verification or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_name": self.task.name,
            "description": self.task.description,
            "user_input": self.task.user_input,
            "difficulty": self.task.difficulty,
            "tags": self.task.tags,
            "success": self.success,
            "result": self.result,
            "verification": self.verification,
            "conversation": self.conversation,
        }


class Synthesizer:
    def __init__(self, model: str = "qwen2.5-coder:1.5b", max_rounds: int = 5) -> None:
        self.model = model
        self.max_rounds = max_rounds

    def synthesize(self, task: GeneratedTask) -> Trajectory:
        workspace = self._setup_workspace(task)
        try:
            ctx = Context()
            reg = PluginRegistry(ctx)
            db_path = Path(workspace) / "benchmark.db"
            reg.register(EventLogger(db_path))
            reg.register(OllamaModel(model=self.model))
            reg.register(FileTools(Path(workspace)))
            reg.register(AgentLoop(max_rounds=self.max_rounds))
            reg.start_all()

            start = time.time()
            result_text = ctx.plugins["agent_loop"].run(task.user_input)
            elapsed = time.time() - start

            conversation = []
            for m in ctx.messages:
                conversation.append({
                    "role": m.role,
                    "content": m.content,
                    "tool_calls": m.tool_calls,
                })

            verifier = TaskVerifier()
            agent_trace = self._build_agent_trace(ctx, task, result_text)
            verification = verifier.verify(self._make_verified_task(task), agent_trace, Path(workspace))

            return Trajectory(
                task=task,
                conversation=conversation,
                result=result_text,
                success=verification.get("legitimate_success", False),
                verification=verification,
            )
        except Exception as e:
            return Trajectory(
                task=task,
                conversation=[],
                result=f"error: {e}",
                success=False,
            )
        finally:
            reg.stop_all()
            ctx.plugins["event_logger"].event_log.close()
            shutil.rmtree(workspace, ignore_errors=True)

    def _setup_workspace(self, task: GeneratedTask) -> str:
        import tempfile
        workspace = tempfile.mkdtemp(prefix=f"synth_{task.name}_")
        if any(t in task.tools_required for t in ["write_file", "list_directory"]):
            for filename in ["a.txt", "b.txt"]:
                Path(workspace, filename).write_text("", encoding="utf-8")
        if "read_file" in task.tools_required:
            src = task.user_input.split()[1] if len(task.user_input.split()) > 1 else "file.txt"
            Path(workspace, src).write_text("preexisting content", encoding="utf-8")
        if "list_directory" in task.tools_required:
            Path(workspace, "file.txt").write_text("preexisting content", encoding="utf-8")
        return workspace

    def _build_agent_trace(self, ctx: Context, task: GeneratedTask, result_text: str = "") -> Dict[str, Any]:
        el = ctx.plugins["event_logger"]
        cont = el.continuity
        session_id = cont.session_id if hasattr(cont, "session_id") else "default"
        events = el.event_log.get_session_events(session_id)
        invocations = [e for e in events if e.type == "tool.invoked"]
        results = [e for e in events if e.type == "tool.result"]

        steps = []
        for i, ev in enumerate(invocations):
            result_ev = next((r for r in results if r.payload.get("call_id") == ev.payload.get("call_id")), None)
            payload = result_ev.payload if result_ev else {}
            steps.append({
                "step_id": i,
                "tool_name": ev.payload.get("tool_name", "unknown"),
                "success": payload.get("success", False),
                "recovery": False,
                "arguments": ev.payload.get("arguments", {}),
            })

        return {"steps": steps, "summary": {}, "result": result_text}

    def _make_verified_task(self, task: GeneratedTask) -> VerifiedBenchmarkTask:
        from benchmark.tasks.verification import TaskVerification, VerificationCheck, VerificationProcedure

        checks = []
        required_paths = []
        required_content = []
        min_writes = 0
        required_steps = ["tool_call"]

        if "write" in task.tools_required:
            if "multi" in task.tags:
                filenames = re.findall(r"\b\w+\.\w+\b", task.user_input)
                for fn in filenames:
                    checks.append(VerificationCheck(kind="file_exists", path=fn))
                min_writes = len(filenames)
            elif "append" in task.tags:
                filename = task.user_input.split()[-1] if len(task.user_input.split()) > 1 else "file.txt"
                checks.append(VerificationCheck(kind="file_exists", path=filename))
                required_paths.append(filename)
            else:
                filename = task.user_input.split()[-1] if "to" in task.user_input else "file.txt"
                checks.append(VerificationCheck(kind="file_exists", path=filename))
                required_paths.append(filename)

        if "read" in task.tools_required:
            filename = task.user_input.split()[1] if len(task.user_input.split()) > 1 else "file.txt"
            checks.append(VerificationCheck(kind="file_exists", path=filename))
            required_paths.append(filename)

        if "list" in task.tools_required:
            checks.append(VerificationCheck(kind="file_exists", path="file.txt"))
            if "search" in task.tags:
                required_steps = ["list_directory", "read_file"]

        if "search" in task.tags:
            target = task.user_input.split()[-1] if len(task.user_input.split()) > 1 else "file.txt"
            required_content = [f"File '{target}'", f"{target} not found", f"does not exist", f"exists"]

        allowed = [t for t in task.tools_required if t in KNOWN_TOOLS]
        if not allowed:
            allowed = list(KNOWN_TOOLS)

        return VerifiedBenchmarkTask(
            name=task.name,
            description=task.description,
            horizon=5,
            setup_fn=lambda: "",
            execute_fn=None,
            verify_fn=lambda ws: True,
            verification=TaskVerification(
                type="artifact",
                checks=checks,
                procedure=VerificationProcedure(
                    allowed_tools=allowed,
                    required_steps=required_steps,
                    max_tool_calls=10,
                    required_paths=required_paths,
                    required_content_contains=required_content,
                    min_files_created=min_writes,
                ),
            ),
            partial_credit_fn=lambda ws: 1.0,
            required_tools=task.tools_required,
            tags=task.tags,
            user_input=task.user_input,
            expected_output="done",
            difficulty=task.difficulty,
        )
