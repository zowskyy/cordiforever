"""Bounded task lane: run a model only on tasks whose outcome an independent deterministic verifier can prove.

A TaskSpec states the instruction, the exact files the task may change, and declarative checks. The runner
never trusts the model's own completion claim: the final state comes only from the checks.

States:
  verified_done     - every check passed, at least one postcondition check proves the requested outcome,
                      and no file outside mutable_paths changed.
  proposal_complete - the caller explicitly accepted an unverifiable proposal (sanity checks only) and they passed.
                      Never authoritative: the change still needs review by a stronger component.
  escalate          - ineligible spec (model never called), agent escalation/error, or any check failed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from .outcomes import EscalationRequired
from .path_candidates import normalize

TaskState = Literal["verified_done", "proposal_complete", "escalate"]

POSTCONDITION_CHECKS = {"file_equals", "file_contains", "json_pointer_equals", "file_absent", "python_call_equals", "python_expr_equals"}
SANITY_CHECKS = {"python_compiles", "json_keys_preserved", "pytest_passes"}
CODE_EXECUTING_CHECKS = {"python_call_equals", "python_expr_equals", "pytest_passes"}
# Checks that run against a copy of the whole workspace rather than one mutable file.
WORKSPACE_CHECKS = {"python_expr_equals", "pytest_passes"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}


@dataclass(frozen=True)
class TaskSpec:
    instruction: str
    mutable_paths: tuple[str, ...]
    checks: tuple[dict[str, Any], ...]
    allow_code_execution: bool = False
    accept_unverified_proposal: bool = False


@dataclass
class CheckResult:
    check: dict[str, Any]
    passed: bool
    detail: str


@dataclass
class BoundedResult:
    state: TaskState
    reason: str
    checks: list[CheckResult] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    agent_answer: str | None = None
    agent_escalation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def eligibility_problems(spec: TaskSpec) -> list[str]:
    problems: list[str] = []
    mutable = [normalize(p) for p in spec.mutable_paths]
    if not mutable:
        problems.append("no mutable_paths: the action is not bounded")
    if any(not p or any(c in p for c in "*?[") or p.startswith("..") for p in mutable):
        problems.append("mutable_paths must be exact workspace-relative paths")
    if not spec.checks:
        problems.append("no acceptance checks")
    for check in spec.checks:
        kind = check.get("type")
        if kind not in POSTCONDITION_CHECKS | SANITY_CHECKS:
            problems.append(f"unknown check type: {kind!r}")
            continue
        if kind in WORKSPACE_CHECKS:
            if kind == "pytest_passes":
                tests = check.get("tests") or []
                if not tests:
                    problems.append("pytest_passes needs at least one public test path or node id")
                if any(Path(str(t).split("::")[0]).is_absolute() or ".." in Path(str(t).split("::")[0]).parts for t in tests):
                    problems.append("pytest_passes tests must be workspace-relative")
            elif not isinstance(check.get("code"), str) or "expected_stdout" not in check:
                problems.append("python_expr_equals needs code and expected_stdout")
        elif normalize(str(check.get("path", ""))) not in mutable:
            problems.append(f"{kind} targets {check.get('path')!r}, which is not in mutable_paths")
        if kind in CODE_EXECUTING_CHECKS and not spec.allow_code_execution:
            problems.append(f"{kind} executes workspace code but allow_code_execution is false")
    has_postcondition = any(c.get("type") in POSTCONDITION_CHECKS for c in spec.checks)
    if not has_postcondition and not spec.accept_unverified_proposal:
        problems.append("no postcondition check proves the requested outcome")
    return problems


def snapshot(workspace: Path) -> dict[str, str]:
    root = workspace.resolve()
    state: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts) or not p.is_file() or p.is_symlink():
            continue
        state[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return state


def _text(workspace: Path, rel: str) -> str | None:
    target = workspace / normalize(rel)
    try:
        return target.read_text(encoding="utf-8") if target.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None


def _pointer_value(doc: Any, pointer: str) -> tuple[bool, Any]:
    segments = [s.replace("~1", "/").replace("~0", "~") for s in pointer.lstrip("/").split("/")] if pointer.startswith("/") else [pointer]
    node = doc
    for seg in segments:
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        elif isinstance(node, list) and seg.isdigit() and int(seg) < len(node):
            node = node[int(seg)]
        else:
            return False, None
    return True, node


def _json_key_paths(value: Any, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return set()
    keys: set[str] = set()
    for k, v in value.items():
        keys.add(f"{prefix}/{k}")
        keys |= _json_key_paths(v, f"{prefix}/{k}")
    return keys


def _workspace_copy(workspace: Path, destination: Path) -> Path:
    target = destination / "ws"
    shutil.copytree(workspace, target, ignore=shutil.ignore_patterns(*_SKIP_DIRS))
    return target


def _run_workspace_check(check: dict[str, Any], workspace: Path) -> CheckResult:
    kind = check["type"]
    timeout = float(check.get("timeout", 60))
    with tempfile.TemporaryDirectory(prefix="cordii-check-") as sandbox:
        copy = _workspace_copy(workspace, Path(sandbox))
        if kind == "python_expr_equals":
            command = [sys.executable, "-c", check["code"]]
        else:
            # Unique --basetemp per invocation: pytest deletes the directory it is given.
            command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(Path(sandbox) / "pytest-tmp"),
                       *[str(t) for t in check["tests"]]]
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTEST_ADDOPTS")}
        env["PYTHONPATH"] = str(copy)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=copy, env=env)
        except subprocess.TimeoutExpired:
            return CheckResult(check, False, "timed out")
    if kind == "python_expr_equals":
        ok = proc.returncode == 0 and proc.stdout.strip() == str(check["expected_stdout"]).strip()
        detail = f"stdout={proc.stdout.strip()[:80]!r} rc={proc.returncode}" + (f" stderr={proc.stderr.strip().splitlines()[-1][:120]!r}" if proc.returncode and proc.stderr.strip() else "")
        return CheckResult(check, ok, detail)
    summary = (proc.stdout.strip().splitlines() or [""])[-1]
    return CheckResult(check, proc.returncode == 0, f"pytest rc={proc.returncode}: {summary[:120]}")


def run_check(check: dict[str, Any], workspace: Path, before_texts: dict[str, str | None]) -> CheckResult:
    kind = check["type"]
    if kind in WORKSPACE_CHECKS:
        return _run_workspace_check(check, workspace)
    path = normalize(str(check.get("path", "")))
    text = _text(workspace, path)
    if kind == "file_absent":
        exists = (workspace / path).exists()
        return CheckResult(check, not exists, "absent" if not exists else "still exists")
    if text is None:
        return CheckResult(check, False, f"{path} missing or unreadable")
    if kind == "file_equals":
        actual = text.strip() if check.get("strip", True) else text
        expected = check["text"].strip() if check.get("strip", True) else check["text"]
        return CheckResult(check, actual == expected, f"content={actual[:80]!r}")
    if kind == "file_contains":
        missing = [s for s in check["substrings"] if s not in text]
        return CheckResult(check, not missing, f"missing={missing}" if missing else "all present")
    if kind in ("json_pointer_equals", "json_keys_preserved"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            return CheckResult(check, False, f"invalid JSON: {exc.msg}")
        if kind == "json_pointer_equals":
            found, value = _pointer_value(doc, check["pointer"])
            ok = found and value == check["value"] and type(value) is type(check["value"])
            return CheckResult(check, ok, f"{check['pointer']}={json.dumps(value) if found else '(missing)'}")
        before = before_texts.get(path)
        try:
            before_keys = _json_key_paths(json.loads(before)) if before is not None else set()
        except json.JSONDecodeError:
            before_keys = set()
        lost = sorted(before_keys - _json_key_paths(doc))
        return CheckResult(check, not lost, f"lost keys={lost}" if lost else "all original keys present")
    if kind == "python_compiles":
        try:
            compile(text, path, "exec")
            return CheckResult(check, True, "compiles")
        except (SyntaxError, ValueError) as exc:
            return CheckResult(check, False, f"syntax error: {exc}")
    if kind == "python_call_equals":
        with tempfile.TemporaryDirectory() as sandbox:
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-c", text + "\n" + check["expression"]],
                    capture_output=True, text=True, timeout=float(check.get("timeout", 10)), cwd=sandbox,
                )
            except subprocess.TimeoutExpired:
                return CheckResult(check, False, "timed out")
        ok = proc.returncode == 0 and proc.stdout.strip() == str(check["expected_stdout"]).strip()
        return CheckResult(check, ok, f"stdout={proc.stdout.strip()[:80]!r} rc={proc.returncode}")
    return CheckResult(check, False, f"unknown check type {kind!r}")


def run_bounded_task(spec: TaskSpec, workspace: Path, run_agent: Callable[[str], str]) -> BoundedResult:
    problems = eligibility_problems(spec)
    if problems:
        return BoundedResult("escalate", "ineligible: " + "; ".join(problems))
    workspace = workspace.resolve()
    mutable = {normalize(p) for p in spec.mutable_paths}
    before = snapshot(workspace)
    before_texts = {normalize(str(c.get("path", ""))): _text(workspace, str(c.get("path", ""))) for c in spec.checks if c.get("type") not in WORKSPACE_CHECKS}
    answer: str | None = None
    agent_escalation: dict[str, Any] | None = None
    failure: str | None = None
    try:
        answer = str(run_agent(spec.instruction))
    except EscalationRequired as exc:
        agent_escalation = exc.outcome.to_dict()
        failure = f"agent escalated: {exc.outcome.reason}"
    except Exception as exc:  # the lane reports any agent failure as an escalation with its cause
        failure = f"agent failed: {type(exc).__name__}: {exc}"
    after = snapshot(workspace)
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    results = [run_check(c, workspace, before_texts) for c in spec.checks]
    out_of_scope = [p for p in changed if p not in mutable]
    results.append(CheckResult({"type": "scope", "mutable_paths": sorted(mutable)}, not out_of_scope,
                               f"changed outside scope: {out_of_scope}" if out_of_scope else "only mutable paths changed"))
    failed = [r for r in results if not r.passed]
    if failed:
        reason = "verification failed: " + "; ".join(f"{r.check['type']} ({r.detail})" for r in failed)
        return BoundedResult("escalate", f"{failure}; {reason}" if failure else reason, results, changed, answer, agent_escalation)
    note = f" ({failure})" if failure else ""
    if any(r.check.get("type") in POSTCONDITION_CHECKS for r in results):
        # The checks are the authority in both directions: a failed agent process does not undo a proven outcome.
        return BoundedResult("verified_done", "all checks passed" + note, results, changed, answer, agent_escalation)
    if failure is not None:
        return BoundedResult("escalate", failure, results, changed, answer, agent_escalation)
    return BoundedResult("proposal_complete", "sanity checks passed; requested outcome not independently proven", results, changed, answer)
