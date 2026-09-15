from __future__ import annotations

import json

from core.bounded_task import TaskSpec, eligibility_problems, run_bounded_task
from core.outcomes import EscalationOutcome, EscalationRequired

BUGGY = "def add(a, b):\n    return a - b\n"
FIX_SPEC = TaskSpec(
    instruction="Fix the bug in add.py: the add function subtracts instead of adding.",
    mutable_paths=("add.py",),
    checks=({"type": "python_call_equals", "path": "add.py", "expression": "print(add(2, 3), add(-1, 1))", "expected_stdout": "5 0"},),
    allow_code_execution=True,
)


def _agent_writing(tmp_path, writes, answer="done"):
    calls = []

    def run(instruction):
        calls.append(instruction)
        for rel, text in writes.items():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text(text, encoding="utf-8")
        return answer

    return run, calls


def test_ineligible_semantic_task_escalates_without_calling_model(tmp_path):
    run, calls = _agent_writing(tmp_path, {})
    result = run_bounded_task(TaskSpec("Fix this bug", ("add.py",), ()), tmp_path, run)
    assert result.state == "escalate" and "no acceptance checks" in result.reason
    assert calls == []


def test_eligibility_rules():
    assert eligibility_problems(FIX_SPEC) == []
    assert "allow_code_execution is false" in " ".join(eligibility_problems(TaskSpec(FIX_SPEC.instruction, ("add.py",), FIX_SPEC.checks)))
    assert "not bounded" in " ".join(eligibility_problems(TaskSpec("x", (), ({"type": "file_absent", "path": "a"},))))
    assert "exact workspace-relative" in " ".join(eligibility_problems(TaskSpec("x", ("*.log",), ({"type": "file_absent", "path": "*.log"},))))
    assert "not in mutable_paths" in " ".join(eligibility_problems(TaskSpec("x", ("a.txt",), ({"type": "file_absent", "path": "b.txt"},))))
    assert "no postcondition" in " ".join(eligibility_problems(TaskSpec("x", ("a.py",), ({"type": "python_compiles", "path": "a.py"},))))
    assert eligibility_problems(TaskSpec("x", ("a.py",), ({"type": "python_compiles", "path": "a.py"},), accept_unverified_proposal=True)) == []


def test_correct_fix_is_verified_done(tmp_path):
    (tmp_path / "add.py").write_text(BUGGY, encoding="utf-8")
    run, _ = _agent_writing(tmp_path, {"add.py": "def add(a, b):\n    return a + b\n"})
    result = run_bounded_task(FIX_SPEC, tmp_path, run)
    assert result.state == "verified_done"
    assert result.changed_paths == ["add.py"]


def test_false_completion_claim_fails_verification(tmp_path):
    # Observed: gemma renamed add -> subtract and said "Task completed successfully."
    (tmp_path / "add.py").write_text(BUGGY, encoding="utf-8")
    run, _ = _agent_writing(tmp_path, {"add.py": "def subtract(a, b):\n    return a - b\n"}, answer="Task completed successfully.")
    result = run_bounded_task(FIX_SPEC, tmp_path, run)
    assert result.state == "escalate" and result.reason.startswith("verification failed: python_call_equals")
    assert result.agent_answer == "Task completed successfully."


def test_change_outside_mutable_paths_fails_scope(tmp_path):
    (tmp_path / "add.py").write_text(BUGGY, encoding="utf-8")
    run, _ = _agent_writing(tmp_path, {"add.py": "def add(a, b):\n    return a + b\n", "stray.py": "x = 1\n"})
    result = run_bounded_task(FIX_SPEC, tmp_path, run)
    assert result.state == "escalate" and "changed outside scope: ['stray.py']" in result.reason


def test_json_postconditions_and_key_preservation(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.json").write_text('{"name": "demo", "port": 3000}', encoding="utf-8")
    spec = TaskSpec("Set port to 8080", ("config/app.json",), (
        {"type": "json_pointer_equals", "path": "config/app.json", "pointer": "/port", "value": 8080},
        {"type": "json_keys_preserved", "path": "config/app.json"},
    ))
    wiped, _ = _agent_writing(tmp_path, {"config/app.json": '{"port": 8080}'})
    result = run_bounded_task(spec, tmp_path, wiped)
    assert result.state == "escalate" and "lost keys=['/name']" in result.reason
    (tmp_path / "config" / "app.json").write_text('{"name": "demo", "port": 3000}', encoding="utf-8")
    string_port, _ = _agent_writing(tmp_path, {"config/app.json": '{"name": "demo", "port": "8080"}'})
    assert run_bounded_task(spec, tmp_path, string_port).state == "escalate"
    (tmp_path / "config" / "app.json").write_text('{"name": "demo", "port": 3000}', encoding="utf-8")
    good, _ = _agent_writing(tmp_path, {"config/app.json": json.dumps({"name": "demo", "port": 8080})})
    assert run_bounded_task(spec, tmp_path, good).state == "verified_done"


def test_agent_escalation_with_unproven_outcome_escalates(tmp_path):
    (tmp_path / "add.py").write_text(BUGGY, encoding="utf-8")
    outcome = EscalationOutcome("repeated_failed_call", "gemma3:1b", 2, 0, ["x"], 0.4)

    def run(instruction):
        raise EscalationRequired(outcome)

    result = run_bounded_task(FIX_SPEC, tmp_path, run)
    assert result.state == "escalate"
    assert result.reason.startswith("agent escalated: repeated_failed_call; verification failed")
    assert result.agent_escalation["reason"] == "repeated_failed_call"


def test_proven_outcome_is_verified_even_if_agent_escalated_afterwards(tmp_path):
    # Observed: the file was created correctly, then the agent tripped repeat detection.
    outcome = EscalationOutcome("repeated_failed_call", "gemma3:1b", 3, 1, ["x"], 0.4)

    def run(instruction):
        (tmp_path / "add.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        raise EscalationRequired(outcome)

    result = run_bounded_task(FIX_SPEC, tmp_path, run)
    assert result.state == "verified_done"
    assert result.reason == "all checks passed (agent escalated: repeated_failed_call)"
    assert result.agent_escalation["reason"] == "repeated_failed_call"


def test_sanity_only_proposal_with_agent_failure_escalates(tmp_path):
    (tmp_path / "util.py").write_text("x = 1\n", encoding="utf-8")
    spec = TaskSpec("Refactor util.py", ("util.py",), ({"type": "python_compiles", "path": "util.py"},), accept_unverified_proposal=True)

    def run(instruction):
        raise RuntimeError("model crashed")

    result = run_bounded_task(spec, tmp_path, run)
    assert result.state == "escalate" and "model crashed" in result.reason


def test_proposal_complete_only_when_explicitly_accepted(tmp_path):
    (tmp_path / "util.py").write_text("x = 1\n", encoding="utf-8")
    spec = TaskSpec("Refactor util.py", ("util.py",), ({"type": "python_compiles", "path": "util.py"},), accept_unverified_proposal=True)
    run, _ = _agent_writing(tmp_path, {"util.py": "X = 1\n"})
    result = run_bounded_task(spec, tmp_path, run)
    assert result.state == "proposal_complete"


def _package(tmp_path, body):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from .ops import add\n", encoding="utf-8")
    (tmp_path / "pkg" / "ops.py").write_text(body, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ops.py").write_text("from pkg import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")


def _workspace_checks(tmp_path):
    from core.bounded_task import run_check

    expr = {"type": "python_expr_equals", "code": "from pkg import add; print(add(2, 3))", "expected_stdout": "5"}
    tests = {"type": "pytest_passes", "tests": ["tests/test_ops.py"]}
    return run_check(expr, tmp_path, {}), run_check(tests, tmp_path, {})


def test_package_expression_and_pytest_checks_fail_then_pass(tmp_path):
    from core.bounded_task import snapshot

    _package(tmp_path, "def add(a, b):\n    return a - b\n")
    before = snapshot(tmp_path)
    expr, tests = _workspace_checks(tmp_path)
    assert not expr.passed and "stdout='-1'" in expr.detail
    assert not tests.passed and "rc=1" in tests.detail
    (tmp_path / "pkg" / "ops.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    expr, tests = _workspace_checks(tmp_path)
    assert expr.passed and tests.passed
    after = snapshot(tmp_path)
    assert set(after) == set(before)  # checks ran on copies: no caches or artifacts in the workspace


def test_workspace_check_eligibility():
    base = dict(instruction="x", mutable_paths=("pkg/ops.py",), allow_code_execution=True)
    ok = TaskSpec(**base, checks=({"type": "python_expr_equals", "code": "print(1)", "expected_stdout": "1"}, {"type": "pytest_passes", "tests": ["tests/test_ops.py::test_add"]}))
    assert eligibility_problems(ok) == []
    assert "workspace-relative" in " ".join(eligibility_problems(TaskSpec(**base, checks=({"type": "pytest_passes", "tests": ["../x.py"]}, {"type": "python_expr_equals", "code": "print(1)", "expected_stdout": "1"}))))
    assert "needs code" in " ".join(eligibility_problems(TaskSpec(**base, checks=({"type": "python_expr_equals"},))))
    no_exec = TaskSpec("x", ("pkg/ops.py",), ({"type": "python_expr_equals", "code": "print(1)", "expected_stdout": "1"},))
    assert "allow_code_execution is false" in " ".join(eligibility_problems(no_exec))
    only_tests = TaskSpec(**base, checks=({"type": "pytest_passes", "tests": ["tests"]},))
    assert "no postcondition" in " ".join(eligibility_problems(only_tests))


def test_code_check_runs_isolated_with_timeout(tmp_path):
    (tmp_path / "add.py").write_text("while True:\n    pass\n", encoding="utf-8")
    spec = TaskSpec(FIX_SPEC.instruction, ("add.py",), ({**FIX_SPEC.checks[0], "timeout": 1},), allow_code_execution=True)
    run, _ = _agent_writing(tmp_path, {})
    result = run_bounded_task(spec, tmp_path, run)
    assert result.state == "escalate" and "timed out" in result.reason
