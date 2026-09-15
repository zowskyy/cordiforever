"""Self-validation of the repository task corpus: structure, leakage boundary, and non-vacuous checks."""

from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from benchmark.repo_task_eval import ORACLE_DIR, REPOS_DIR, apply_patch, repo_files, resolve_hidden_tests, run_oracle, seed_workspace
from benchmark.repo_tasks import TASKS
from core.bounded_task import POSTCONDITION_CHECKS, eligibility_problems, run_bounded_task, run_check


def _repo_text(repo: str) -> str:
    root = REPOS_DIR / repo
    return "\n".join((root / rel).read_text(encoding="utf-8") for rel in sorted(repo_files(root)))


def test_corpus_structure():
    names = [t.name for t in TASKS]
    assert len(names) == len(set(names)) == 40
    assert {t.split for t in TASKS} == {"dev", "heldout"}
    assert sum(t.split == "dev" for t in TASKS) == sum(t.split == "heldout" for t in TASKS) == 20
    for repo in ("mathlib", "configsvc", "textkit", "inventory"):
        per_repo = [t for t in TASKS if t.repo == repo]
        assert len(per_repo) == 10
        assert sum(t.expected_outcome == "escalate" for t in per_repo) == 2
    for task in TASKS:
        assert eligibility_problems(task.public_spec) == [], task.name
        assert task.public_spec.instruction == task.prompt
        files = repo_files(REPOS_DIR / task.repo)
        if task.expected_outcome == "verified_done":
            assert task.reference_patch, task.name
            assert set(task.reference_patch) <= set(task.public_spec.mutable_paths), task.name
            assert set(task.gold_files) <= set(task.reference_patch) | files, task.name
            assert len(resolve_hidden_tests(task)) == 1, task.name
            assert not task.missing_fact
        else:
            assert task.reference_patch is None and task.oracle.hidden_test_ids == () and task.missing_fact, task.name


def test_insufficient_evidence_facts_are_absent_from_repos():
    # Mechanical absence check of the declared literal facts; not a proof that the task is unsolvable.
    for task in (t for t in TASKS if t.expected_outcome == "escalate"):
        text = _repo_text(task.repo)
        present = [fact for fact in task.missing_fact if fact in text]
        assert present == [], f"{task.name}: {present}"


def test_leakage_boundary():
    hidden_names = {p.name for p in ORACLE_DIR.rglob("*.py")}
    hidden_asserts = {line.strip() for p in ORACLE_DIR.rglob("*.py") for line in p.read_text(encoding="utf-8").splitlines() if line.strip().startswith("assert ")}
    assert len(hidden_names) == 32
    for repo in {t.repo for t in TASKS}:
        text = _repo_text(repo)
        assert "oracle" not in text.lower()
        assert not [n for n in hidden_names if n in text]
    assert not any(p.name in hidden_names for p in REPOS_DIR.rglob("*.py"))
    for task in TASKS:
        public = json.dumps(asdict(task.public_spec)) + task.prompt
        assert "oracle" not in public.lower() and "hidden" not in public.lower(), task.name
        assert not [n for n in hidden_names if n in public], task.name
        assert not [a for a in hidden_asserts if a in public], task.name


def _validate(task) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cordii-corpus-") as tmp:
        workspace = seed_workspace(task, Path(tmp))
        untouched = [run_check(c, workspace, {}) for c in task.public_spec.checks]
        post = [r for r in untouched if r.check["type"] in POSTCONDITION_CHECKS]
        if not post or all(r.passed for r in post):
            problems.append(f"{task.name}: postconditions already pass on untouched repo")
        core = [r for r in untouched if r.check["type"] == "pytest_passes"]
        if not all(r.passed for r in core):
            problems.append(f"{task.name}: regression tests fail on untouched repo: {[r.detail for r in core]}")
        if task.expected_outcome == "escalate":
            return problems
        before = run_oracle(task, workspace)
        if before["passed"] is not False:
            problems.append(f"{task.name}: hidden oracle does not fail on untouched repo")
        result = run_bounded_task(task.public_spec, workspace, lambda _instruction: apply_patch(workspace, task.reference_patch) or "done")
        if result.state != "verified_done":
            problems.append(f"{task.name}: reference patch not verified: {result.reason}")
        after = run_oracle(task, workspace)
        if after["passed"] is not True:
            problems.append(f"{task.name}: hidden oracle fails on reference patch: {after['detail'][-400:]}")
    return problems


def test_every_task_checks_are_non_vacuous_and_reference_patches_verify():
    with ThreadPoolExecutor(max_workers=4) as pool:
        problems = [p for result in pool.map(_validate, TASKS) for p in result]
    assert problems == []
