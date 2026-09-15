"""
Three-layer benchmark verification:
1. Artifact verification (file system state)
2. Execution verification (tests/commands)
3. Procedure verification (agent trajectory compliance)
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from core.messages import Message


PLACEHOLDER_PATHS = {"path/to", "path/to/", "<", ">", "placeholder", "example.com"}
PLACEHOLDER_CONTENT = {
    "fix issue #1 in vscode.",
    "modify relevant files and run tests.",
    "fix the bug",
    "implement this",
}
KNOWN_TOOLS = {"read_file", "write_file", "list_directory", "read_json", "run_command"}


@dataclass
class VerificationCheck:
    kind: str
    path: str = ""
    expected: str = ""
    mode: str = "exact"
    timeout: int = 30


@dataclass
class VerificationProcedure:
    allowed_tools: List[str] = field(default_factory=list)
    disallowed_tools: List[str] = field(default_factory=list)
    required_steps: List[str] = field(default_factory=list)
    max_tool_calls: Optional[int] = None
    max_recovery_attempts: Optional[int] = None
    required_paths: List[str] = field(default_factory=list)
    required_content_contains: List[str] = field(default_factory=list)
    required_content_not_contains: List[str] = field(default_factory=list)
    min_files_created: int = 0


@dataclass
class TaskVerification:
    type: str = "artifact"
    checks: List[VerificationCheck] = field(default_factory=list)
    procedure: Optional[VerificationProcedure] = None
    test_suite: Optional[Dict[str, Any]] = None
    setup_command: Optional[List[str]] = None
    repo: str = ""


@dataclass
class VerifiedBenchmarkTask:
    name: str
    description: str
    horizon: int
    setup_fn: Callable
    execute_fn: Optional[Callable]
    verify_fn: Optional[Callable]
    verification: TaskVerification
    partial_credit_fn: Optional[Callable] = None
    required_tools: List[str] = field(default_factory=list)
    stress_recovery: bool = False
    stress_context_folding: bool = False
    tags: List[str] = field(default_factory=list)
    user_input: str = ""
    model_responses: List[Message] = field(default_factory=list)
    expected_output: str = ""
    difficulty: str = "medium"


class ArtifactVerifier:
    def check(self, task: VerifiedBenchmarkTask, workspace_root: str, agent_trace: Dict[str, Any] = None) -> Dict[str, Any]:
        checks = task.verification.checks
        procedure = task.verification.procedure or {}
        results = {}
        all_passed = True

        for i, check in enumerate(checks):
            key = f"check_{i}"
            passed = False

            if check.kind == "file_exists":
                passed = (workspace_root / check.path).exists()

            elif check.kind == "file_content":
                path = workspace_root / check.path
                if not path.exists():
                    passed = False
                else:
                    try:
                        content = path.read_text(encoding="utf-8")
                        if check.mode == "exact":
                            passed = content.strip() == check.expected.strip()
                        elif check.mode == "contains":
                            passed = check.expected in content
                        elif check.mode == "regex":
                            passed = re.search(check.expected, content) is not None
                        else:
                            passed = False
                    except (OSError, UnicodeDecodeError):
                        passed = False

            elif check.kind == "file_not_exists":
                passed = not (workspace_root / check.path).exists()

            elif check.kind == "directory_exists":
                passed = (workspace_root / check.path).is_dir()

            elif check.kind == "command_output":
                try:
                    result = subprocess.run(
                        check.expected,
                        cwd=workspace_root,
                        capture_output=True,
                        text=True,
                        timeout=check.timeout,
                    )
                    passed = result.returncode == 0
                except (subprocess.TimeoutExpired, OSError):
                    passed = False

            results[key] = {
                "passed": passed,
                "check": check.kind,
                "path": getattr(check, "path", ""),
            }
            if not passed:
                all_passed = False

        required_paths = getattr(procedure, "required_paths", []) or []
        for path in required_paths:
            if not (workspace_root / path).exists():
                all_passed = False
                results[f"required_path_{path}"] = {
                    "passed": False,
                    "check": "required_path",
                    "path": path,
                }

        required_content = getattr(procedure, "required_content_contains", []) or []
        for content in required_content:
            found = False
            for f in workspace_root.rglob("*"):
                if f.is_file():
                    try:
                        if content in f.read_text(encoding="utf-8", errors="ignore"):
                            found = True
                            break
                    except (OSError, UnicodeDecodeError):
                        continue
            if not found:
                all_passed = False
                results[f"required_content_{content}"] = {
                    "passed": False,
                    "check": "required_content",
                    "expected": content,
                }

        return {"passed": all_passed, "checks": results}


class ExecutionVerifier:
    def run_tests(self, task: VerifiedBenchmarkTask, workspace_root: str) -> Dict[str, Any]:
        suite = task.verification.test_suite
        if not suite:
            return {"skipped": True}

        repo_root = workspace_root
        if task.verification.repo:
            repo_root = workspace_root / task.verification.repo

        if task.verification.setup_command:
            try:
                setup_result = subprocess.run(
                    task.verification.setup_command,
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if setup_result.returncode != 0:
                    return {
                        "passed": False,
                        "setup_failed": True,
                        "error": setup_result.stderr,
                    }
            except (subprocess.TimeoutExpired, OSError) as exc:
                return {"passed": False, "setup_failed": True, "error": str(exc)}

        try:
            result = subprocess.run(
                suite["command"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=suite.get("timeout", 60),
            )
            return {
                "passed": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode,
            }
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"passed": False, "error": str(exc)}


class ProcedureVerifier:
    def check(self, task: VerifiedBenchmarkTask, agent_trace: Dict[str, Any]) -> Dict[str, Any]:
        procedure = task.verification.procedure
        if not procedure:
            return {"passed": True, "violations": []}

        steps = agent_trace.get("steps", [])
        tools_used = [step.get("tool_name", "") for step in steps]
        tool_counts: Dict[str, int] = {}
        violations = []

        for tool in tools_used:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

        if procedure.disallowed_tools:
            disallowed = set(tools_used) & set(procedure.disallowed_tools)
            if disallowed:
                violations.append(f"used_disallowed_tools: {sorted(disallowed)}")

        if procedure.allowed_tools:
            unknown = set(tools_used) - set(procedure.allowed_tools)
            if unknown:
                violations.append(f"used_unknown_tools: {sorted(unknown)}")

        for step in steps:
            tool_name = step.get("tool_name", "")
            args = step.get("arguments", {})
            if tool_name and tool_name not in KNOWN_TOOLS:
                violations.append(f"unknown_tool: {tool_name}")
            path = args.get("path", "") if isinstance(args, dict) else ""
            if isinstance(path, str):
                for placeholder in PLACEHOLDER_PATHS:
                    if placeholder in path.lower():
                        violations.append(f"placeholder_path: {path}")
                        break
            content = args.get("content", "") if isinstance(args, dict) else ""
            if isinstance(content, str) and content:
                for placeholder in PLACEHOLDER_CONTENT:
                    if placeholder in content.lower():
                        violations.append(f"placeholder_content: {content[:50]}")
                        break

        for required in procedure.required_steps:
            if not any(self._matches_step_type(step, required) for step in steps):
                violations.append(f"missing_required_step: {required}")

        if procedure.max_tool_calls is not None and len(steps) > procedure.max_tool_calls:
            violations.append(f"too_many_tool_calls: {len(steps)} > {procedure.max_tool_calls}")

        if procedure.max_recovery_attempts is not None:
            recovery_count = sum(1 for s in steps if s.get("recovery", False))
            if recovery_count > procedure.max_recovery_attempts:
                violations.append(
                    f"too_many_recovery_attempts: {recovery_count} > {procedure.max_recovery_attempts}"
                )

        min_files = getattr(procedure, "min_files_created", 0) or 0
        if min_files > 0:
            write_count = tool_counts.get("write_file", 0)
            if write_count < min_files:
                violations.append(f"insufficient_writes: {write_count} < {min_files}")

        if "search" in getattr(task, "tags", []):
            result_text = agent_trace.get("result", "")
            target = ""
            if task.user_input:
                parts = task.user_input.split()
                if len(parts) >= 2:
                    target = parts[-1]
            if target and target not in result_text and "not found" not in result_text.lower() and "does not exist" not in result_text.lower():
                if not any(target in step.get("arguments", {}).get("path", "") for step in steps if isinstance(step.get("arguments"), dict)):
                    violations.append(f"search_result_missing: {target}")

        return {"passed": len(violations) == 0, "violations": violations}

    def _matches_step_type(self, step: Dict[str, Any], step_type: str) -> bool:
        tool = step.get("tool_name", "")
        if step_type == "tool_call":
            return bool(tool)
        if step_type == "read_original":
            return tool == "read_file"
        if step_type == "edit":
            return tool == "write_file"
        if step_type == "run_tests":
            return tool == "run_command" and "test" in str(step.get("arguments", {}))
        return tool == step_type


class TaskVerifier:
    def __init__(self):
        self.artifact = ArtifactVerifier()
        self.execution = ExecutionVerifier()
        self.procedure = ProcedureVerifier()

    def verify(
        self,
        task: VerifiedBenchmarkTask,
        agent_trace: Dict[str, Any],
        workspace_root: str,
    ) -> Dict[str, Any]:
        artifact = self.artifact.check(task, workspace_root, agent_trace)
        execution = self.execution.run_tests(task, workspace_root)
        procedure = self.procedure.check(task, agent_trace)

        if task.difficulty == "trivial":
            procedure_ok = artifact["passed"]
            procedure = {"passed": procedure_ok, "violations": [] if procedure_ok else ["artifact_failed"]}
        else:
            procedure_ok = procedure["passed"]

        legitimate_success = (
            artifact["passed"]
            and execution.get("passed", True)
            and procedure_ok
        )

        return {
            "legitimate_success": legitimate_success,
            "artifact_ok": artifact["passed"],
            "execution_ok": execution.get("passed", True),
            "procedure_ok": procedure_ok,
            "artifact_details": artifact,
            "execution_details": execution,
            "procedure_details": procedure,
        }
