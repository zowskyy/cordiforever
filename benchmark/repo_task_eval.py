"""Repository-task evaluator with an independent hidden-test oracle.

Runs each RepoTask through the production bounded lane (core.bounded_task.run_bounded_task) and then judges the
final workspace with its OWN oracle: hidden tests (resolved here, from ids) executed by a separate pytest
subprocess. The oracle never calls core.bounded_task.run_check, so a verifier bug cannot make lane and oracle agree.

Conditions share one explicit harness policy; only the named factor differs:
  gemma_constrained vs qwen_constrained  -> model identity (primary comparison)
  qwen_constrained  vs qwen_native       -> action interface (secondary comparison)

Rows are appended to JSONL with flush + fsync, keyed by a fingerprint of everything that affects the result.
Between conditions the model is unloaded (keep_alive 0) and /api/ps is polled until it is released.

Usage:
    python benchmark/repo_task_eval.py --condition gemma_constrained --split dev
    python benchmark/repo_task_eval.py --condition all --split dev
    python benchmark/repo_task_eval.py --condition all --split dev --summary-only
"""

from __future__ import annotations

import argparse
import hashlib
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.action_validity import action_violation
from benchmark.agent_task_eval import damaged_files, rejection_outcomes
from benchmark.repo_tasks import TASKS, RepoTask
from core.bounded_task import run_bounded_task
from core.diagnosis import evidence_line_span, target_line_span
from core.path_candidates import normalize
from main import build_application

REPOS_DIR = REPO_ROOT / "benchmark" / "repos"
ORACLE_DIR = REPO_ROOT / "benchmark" / "oracle"
RESULTS = REPO_ROOT / "benchmark" / "results" / "repo_task_eval.jsonl"
OLLAMA = "http://127.0.0.1:11434"
_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}

HARNESS_POLICY: dict[str, Any] = {
    "sampling": {"temperature": 0.0, "num_predict": 2048},
    "require_read_before_write": True,
    "repeat_retry_temperature": 0.4,
    "require_known_paths": True,
    "require_read_named_files": True,
    "structured_edits": False,
    "ground_request_paths": False,
    "array_guidance": False,
}
CONDITIONS: dict[str, dict[str, Any]] = {
    "gemma_constrained": {"model": "gemma3:1b", "overrides": {**HARNESS_POLICY, "constrained_actions": True, "text_tool_protocol": True}},
    "qwen_constrained": {"model": "qwen2.5-coder:1.5b", "overrides": {**HARNESS_POLICY, "constrained_actions": True, "text_tool_protocol": True}},
    "qwen_native": {"model": "qwen2.5-coder:1.5b", "overrides": {**HARNESS_POLICY, "constrained_actions": False, "text_tool_protocol": False}},
}
# End-to-end L1: identical to the constrained conditions except deterministic request grounding (evidence gate off).
CONDITIONS["gemma_L1"] = {"model": "gemma3:1b", "overrides": {**CONDITIONS["gemma_constrained"]["overrides"], "targeted_grounding": True}}
CONDITIONS["qwen_L1"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_constrained"]["overrides"], "targeted_grounding": True}}
# Gate diagnose_v1 (benchmark/gates/diagnose_v1.md): complete read views held fixed; only diagnose_before_mutation differs.
for _prefix in ("gemma", "qwen"):
    CONDITIONS[f"{_prefix}_fullread"] = {"model": CONDITIONS[f"{_prefix}_L1"]["model"], "overrides": {**CONDITIONS[f"{_prefix}_L1"]["overrides"], "full_read_views": True}}
    CONDITIONS[f"{_prefix}_diagnose"] = {"model": CONDITIONS[f"{_prefix}_L1"]["model"], "overrides": {**CONDITIONS[f"{_prefix}_fullread"]["overrides"], "diagnose_before_mutation": True}}
# Gate gemma_progress_v1 (benchmark/gates/gemma_progress_v1.md): control = gemma_fullread; only progress_recovery differs.
CONDITIONS["gemma_progress"] = {"model": "gemma3:1b", "overrides": {**CONDITIONS["gemma_fullread"]["overrides"], "progress_recovery": True}}
# Gate qwen_evidence_v1 (benchmark/gates/qwen_evidence_v1.md): control = qwen_diagnose; only read_before_evidence differs.
CONDITIONS["qwen_evidence"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_diagnose"]["overrides"], "read_before_evidence": True}}
# Gate qwen_extract_v1 (benchmark/gates/qwen_extract_v1.md): control = qwen_evidence; only evidence_extraction differs.
CONDITIONS["qwen_extract"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_evidence"]["overrides"], "evidence_extraction": True}}
# Gate qwen_localedit_v1 (benchmark/gates/qwen_localedit_v1.md): control = qwen_extract; only localized_edits differs.
CONDITIONS["qwen_localedit"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_extract"]["overrides"], "localized_edits": True}}
# Gate qwen_selectorkind_v1 (benchmark/gates/qwen_selectorkind_v1.md): control = qwen_localedit; only explicit_selector_kind differs.
CONDITIONS["qwen_selectorkind"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_localedit"]["overrides"], "explicit_selector_kind": True}}
# Gate qwen_astnoop_v1 (benchmark/gates/qwen_astnoop_v1.md): control = qwen_selectorkind; only ast_noop_refusal differs.
CONDITIONS["qwen_astnoop"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_selectorkind"]["overrides"], "ast_noop_refusal": True}}
# Gate qwen_donelatch_v1 (benchmark/gates/qwen_donelatch_v1.md): control = qwen_astnoop; only completion_requires_mutation_success differs.
CONDITIONS["qwen_donelatch"] = {"model": "qwen2.5-coder:1.5b", "overrides": {**CONDITIONS["qwen_astnoop"]["overrides"], "completion_requires_mutation_success": True}}
MAX_ROUNDS = 12
HARNESS_SOURCES = ("plugins/agent/loop.py", "plugins/agent/schema_router.py", "plugins/tools/file.py", "plugins/model/ollama.py",
                   "core/bounded_task.py", "core/path_candidates.py", "core/structured_edit.py", "core/calibration.py", "main.py",
                   "core/grounding.py", "core/repo_index.py", "core/diagnosis.py",
                   "benchmark/repo_task_eval.py", "benchmark/repo_tasks.py")


# ------------------------------------------------------------------ oracle (evaluator-only)
def resolve_hidden_tests(task: RepoTask) -> list[Path]:
    paths = [ORACLE_DIR / task.repo / "hidden" / f"test_{test_id}.py" for test_id in task.oracle.hidden_test_ids]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"hidden tests missing for {task.name}: {missing}")
    return paths


def run_oracle(task: RepoTask, workspace: Path, timeout: float = 120.0) -> dict[str, Any]:
    """Independent judge: copy the workspace, add hidden tests, run a separate pytest process."""
    hidden = resolve_hidden_tests(task)
    if not hidden:
        return {"applicable": False, "passed": None, "detail": "no hidden tests (insufficient-evidence task)"}
    with tempfile.TemporaryDirectory(prefix="cordii-oracle-") as sandbox:
        copy = Path(sandbox) / "ws"
        shutil.copytree(workspace, copy, ignore=shutil.ignore_patterns(*_SKIP))
        oracle_tests = copy / "_oracle_hidden"
        oracle_tests.mkdir()
        for path in hidden:
            shutil.copy2(path, oracle_tests / path.name)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTEST_ADDOPTS")}
        env.update({"PYTHONPATH": str(copy), "PYTHONDONTWRITEBYTECODE": "1"})
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(Path(sandbox) / "oracle-basetemp"), "_oracle_hidden"]
        try:
            proc = subprocess.run(command, cwd=copy, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"applicable": True, "passed": False, "detail": "oracle timed out"}
    output = (proc.stdout + proc.stderr).strip()
    passed = proc.returncode == 0 and " passed" in proc.stdout and " failed" not in proc.stdout and " error" not in proc.stdout
    return {"applicable": True, "passed": passed, "detail": output[-2000:]}


# ------------------------------------------------------------------ workspace helpers
def seed_workspace(task: RepoTask, destination: Path) -> Path:
    workspace = destination / "ws"
    shutil.copytree(REPOS_DIR / task.repo, workspace, ignore=shutil.ignore_patterns(*_SKIP))
    return workspace


def apply_patch(workspace: Path, patch: dict[str, str]) -> None:
    for rel, text in patch.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")


def repo_files(workspace: Path) -> set[str]:
    return {p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file() and not any(s in p.parts for s in _SKIP)}


# ------------------------------------------------------------------ metrics
_MUTATING = ("write_file", "replace_text", "patch_json", "edit_symbol")


def localization_metrics(timeline: list[tuple[str, dict[str, Any]]], gold_files: tuple[str, ...]) -> dict[str, Any]:
    gold = {normalize(g) for g in gold_files}
    read_order: list[str] = []
    mutated: list[str] = []
    touch_order: list[str] = []
    for etype, payload in timeline:
        if etype != "tool.result" or not payload.get("success"):
            continue
        tool = payload.get("tool")
        path = normalize(str((payload.get("arguments") or {}).get("path") or ""))
        if not path:
            continue
        if tool == "read_file":
            if path not in read_order:
                read_order.append(path)
            touch_order.append(path)
        elif tool in _MUTATING:
            if path not in mutated:
                mutated.append(path)
            touch_order.append(path)
    first_gold_index = next((i for i, p in enumerate(dict.fromkeys(touch_order)) if p in gold), None)
    return {
        "files_read": read_order,
        "files_mutated": mutated,
        "read_recall": round(len(gold & set(read_order)) / len(gold), 3) if gold else None,
        "read_precision": round(len(gold & set(read_order)) / len(read_order), 3) if read_order else None,
        "mutation_precision": round(len(gold & set(mutated)) / len(mutated), 3) if mutated else None,
        "gold_first_touch": bool(touch_order) and touch_order[0] in gold,
        "first_gold_rank": first_gold_index,
        "gold_edit_recall": round(len(gold & set(mutated)) / len(gold), 3) if gold else None,
    }


_TEXT_HEAD = 300
_DIFF_LIMIT = 3000


def _summarize_arg(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _TEXT_HEAD:
        return {"chars": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()[:16], "head": value[:_TEXT_HEAD]}
    return value


def call_log(timeline: list[tuple[str, dict[str, Any]]], seed_texts: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every executed or refused agent-loop call (round, tool, summarized args, outcome, result head) and, for each
    successful read, how much of the file the model was actually shown. `complete` compares the text the model
    received with the seeded file; it is None when the file was mutated earlier in the run (seed no longer applies)."""
    calls: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    mutated: set[str] = set()
    round_no = 0
    for etype, payload in timeline:
        if etype == "turn.round":
            round_no += 1
            continue
        if etype != "tool.result" or "tool" not in payload:
            continue
        tool = payload["tool"]
        arguments = payload.get("arguments") or {}
        result = payload.get("result")
        text = result if isinstance(result, str) else json.dumps(result, default=str)
        success = bool(payload.get("success"))
        calls.append({"round": round_no, "tool": tool, "args": {k: _summarize_arg(v) for k, v in arguments.items()},
                      "success": success, "result_chars": len(text), "result_head": text[:_TEXT_HEAD],
                      **({"recovery": payload["recovery"]} if payload.get("recovery") else {})})
        path = normalize(str(arguments.get("path") or ""))
        if not (success and path):
            continue
        if tool == "read_file":
            seed = None if path in mutated else seed_texts.get(path)
            views.append({"round": round_no, "path": path, "file_chars": len(seed) if seed is not None else None,
                          "shown_chars": len(text), "complete": (text == seed) if seed is not None else None})
        elif tool in _MUTATING or tool == "delete_file":
            mutated.add(path)
    return calls, views


def write_diffs(workspace: Path, seed_texts: dict[str, str], seeded: set[str]) -> dict[str, Any]:
    """Unified diff (capped) for each changed seeded text file; created and deleted files are listed explicitly."""
    import difflib

    final = repo_files(workspace)
    diffs: dict[str, Any] = {}
    for rel in sorted(seed_texts):
        target = workspace / rel
        if not target.is_file():
            diffs[rel] = {"deleted": True}
            continue
        after = target.read_text(encoding="utf-8", errors="replace")
        if after != seed_texts[rel]:
            diff = "".join(difflib.unified_diff(seed_texts[rel].splitlines(keepends=True), after.splitlines(keepends=True), rel, rel))
            diffs[rel] = {"diff": diff[:_DIFF_LIMIT], "truncated": len(diff) > _DIFF_LIMIT}
    for rel in sorted(final - seeded):
        text = (workspace / rel).read_text(encoding="utf-8", errors="replace")
        diffs[rel] = {"created": True, "chars": len(text), "head": text[:_TEXT_HEAD]}
    for rel in sorted(seeded - final - set(seed_texts)):
        diffs[rel] = {"deleted": True}
    return diffs


def defect_lines(seed_text: str, reference_text: str) -> set[int]:
    """1-based seed lines the reference patch changes; for a pure insertion, the lines before and at the insertion point."""
    import difflib

    seed_lines, ref_lines = seed_text.splitlines(), reference_text.splitlines()
    lines: set[int] = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(a=seed_lines, b=ref_lines, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            lines.update(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            lines.update(n for n in (i1, i1 + 1) if 1 <= n <= max(len(seed_lines), 1))
    return lines


def diagnosis_records(timeline: list[tuple[str, dict[str, Any]]], task: RepoTask, seed_texts: dict[str, str]) -> list[dict[str, Any]]:
    """Each diagnose call with an evaluator-side defect-hit judgement (independent of the loop's guard)."""
    gold = {normalize(g) for g in task.gold_files}
    reference = {normalize(k): v for k, v in (task.reference_patch or {}).items()}
    records = []
    read_paths: set[str] = set()
    pending_refusal = False  # a guard rejection is followed by the loop's own failed tool.result for the same call
    for etype, payload in timeline:
        if etype == "guard.rejected" and payload.get("tool") == "diagnose":
            pending_refusal = True
            records.append({"path": normalize(str(payload.get("path") or "")), "success": False, "refused": payload.get("reason"),
                            "pre_read": normalize(str(payload.get("path") or "")) not in read_paths,
                            "evidence_head": "", "seed_span": None, "localized": False, "hits_defect": False, "hits_defect_localized": False})
            continue
        if etype != "tool.result":
            continue
        if payload.get("tool") == "read_file" and payload.get("success"):
            read_paths.add(normalize(str((payload.get("arguments") or {}).get("path") or "")))
        if payload.get("tool") != "diagnose":
            continue
        if pending_refusal:
            pending_refusal = False
            continue
        arguments = payload.get("arguments") or {}
        path = normalize(str(arguments.get("path") or ""))
        evidence = str(arguments.get("evidence") or "")
        target = arguments.get("target")
        snapshot_matches_seed = None
        if target is not None:  # qwen_extract_v1: span from the selector, computed on the seed file
            span = target_line_span(path, seed_texts[path], str(target)) if path in seed_texts else None
            found = re.search(r"snapshot_sha256: ([0-9a-f]{64})", str(payload.get("result") or ""))
            if found and path in seed_texts:
                snapshot_matches_seed = found.group(1) == hashlib.sha256(seed_texts[path].encode("utf-8")).hexdigest()
            if snapshot_matches_seed is False:
                span = None  # hit undetermined: the model read a changed file, not the seed
        else:
            span = evidence_line_span(seed_texts[path], evidence) if path in seed_texts else None
        localized = span is not None and (span[1] - span[0] + 1) <= localization_cap(seed_texts[path])
        hits = None
        if path in gold and path in reference and path in seed_texts:
            region = defect_lines(seed_texts[path], reference[path])
            widened = {n + d for n in region for d in (-1, 0, 1)}
            hits = span is not None and bool(set(range(span[0], span[1] + 1)) & widened)
        success = bool(payload.get("success"))
        records.append({"path": path, "success": success, "refused": None, "pre_read": path not in read_paths,
                        "target": target, "snapshot_matches_seed": snapshot_matches_seed,
                        "evidence_head": evidence[:_TEXT_HEAD], "seed_span": list(span) if span else None,
                        "localized": localized, "hits_defect": success and bool(hits),
                        "hits_defect_localized": success and bool(hits) and localized})
    return records


def localization_cap(seed_text: str) -> int:
    """Gate qwen_evidence_v1: a quote is localized if it spans at most max(3, file_lines // 4) lines."""
    return max(3, len(seed_text.splitlines()) // 4)


def invalid_language_files(workspace: Path, paths: list[str]) -> list[str]:
    """Paths that exist but no longer compile (.py) or parse (.json)."""
    invalid = []
    for rel in paths:
        target = workspace / rel
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        try:
            if rel.endswith(".py"):
                compile(text, rel, "exec")
            elif rel.endswith(".json"):
                json.loads(text)
        except (SyntaxError, ValueError):
            invalid.append(rel)
    return invalid


def failure_split(task: RepoTask, condition: str, oracle_passed: bool | None, read_views: list[dict[str, Any]],
                  diagnoses: list[dict[str, Any]], diffs: dict[str, Any], damaged: list[str], invalid: list[str]) -> str | None:
    """Pre-registered split (gate diagnose_v1) for solvable rows that fail the oracle."""
    if task.expected_outcome != "verified_done" or oracle_passed:
        return None
    gold = [normalize(g) for g in task.gold_files]
    shown = {v["path"] for v in read_views if v["complete"] is True}
    if not all(g in shown for g in gold):
        return "no_gold_view"
    if not CONDITIONS[condition]["overrides"].get("diagnose_before_mutation"):
        return "gold_viewed_failed"
    if not any(d["hits_defect"] for d in diagnoses):
        return "gold_viewed_no_diagnosis_hit"
    changed = [g for g in gold if "diff" in (diffs.get(g) or {})]
    if not changed or any(g in damaged or g in invalid for g in changed):
        return "mechanical_failure"
    return "wrong_edit_choice"


_PROPOSED_MUTATIONS = ("write", "replace", "patch_json", "delete", "edit")


def _proposed_actions(model_outputs: list[str]) -> list[dict[str, Any]]:
    """The {"tool", "args"} action the model emitted in each reply (text protocol); unparsable replies are skipped."""
    actions = []
    for output in model_outputs:
        try:
            action = json.loads(output.split(" [tool_calls]")[0])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(action, dict) and isinstance(action.get("args"), dict):
            actions.append(action)
    return actions


def progress_metrics(row: dict[str, Any], task: RepoTask, workspace_files: set[str]) -> dict[str, Any]:
    """Frozen per-task definitions of gate gemma_progress_v1 (computed from recorded rows, independent of the loop)."""
    gold = {normalize(g) for g in task.gold_files}
    actions = _proposed_actions(row["model_outputs"])
    ok_reads = {normalize(str(c["args"].get("path") or "")) for c in row["calls"] if c["tool"] == "read_file" and c["success"]}
    read_counts: dict[str, int] = {}
    for action in actions:
        if action["tool"] == "read":
            path = normalize(str(action["args"].get("path") or ""))
            read_counts[path] = read_counts.get(path, 0) + 1
    seen_gold = opportunity = False
    for call in row["calls"]:
        path = normalize(str(call["args"].get("path") or ""))
        if call["tool"] == "read_file" and call["success"] and path in gold:
            seen_gold = True
        if seen_gold and call["tool"] in _MUTATING and path in gold:
            opportunity = True
    if seen_gold and not opportunity:
        opportunity = any(a["tool"] in _PROPOSED_MUTATIONS and normalize(str(a["args"].get("path") or "")) in gold for a in actions)
    reads = [normalize(str(a["args"].get("path") or "")) for a in actions if a["tool"] == "read"]
    successful_then_same = sum(1 for i, p in enumerate(reads[:-1]) if p in ok_reads and p in workspace_files and reads[i + 1] == p)
    missing_then_same = sum(1 for i, p in enumerate(reads[:-1]) if p not in workspace_files and reads[i + 1] == p)
    return {
        "edit_opportunity": opportunity if task.expected_outcome == "verified_done" else None,
        "reread_loop": any(p in ok_reads and p in workspace_files and n >= 2 for p, n in read_counts.items()),
        "missing_read_loop": any(p not in workspace_files and n >= 2 for p, n in read_counts.items()),
        "read_proposals_existing_successful": sum(1 for p in reads if p in ok_reads and p in workspace_files),
        "successful_read_followed_by_same": successful_then_same,
        "read_proposals_missing": sum(1 for p in reads if p not in workspace_files),
        "missing_read_followed_by_same": missing_then_same,
        "executed_edit": any(c["tool"] in _MUTATING and c["success"] for c in row["calls"]),
        "recoveries": {state: sum(1 for c in row["calls"] if c.get("recovery") == state) for state in ("repeated_successful_read", "repeated_missing_path")},
    }


def experiment_identity(condition: str, digest: str, corpus: str, harness: str, gate: Path | None) -> dict[str, Any]:
    """Mechanical provenance stored on every row. The gate judges results, so it is recorded here and is NOT part of
    the run fingerprint (changing a gate must not invalidate or rerun completed runs)."""
    overrides = CONDITIONS[condition]["overrides"]
    return {
        "condition": condition, "model": CONDITIONS[condition]["model"], "model_digest": digest,
        "corpus_sha256": corpus, "harness_sha256": harness,
        "overrides_sha256": hashlib.sha256(json.dumps(overrides, sort_keys=True, default=str).encode()).hexdigest(),
        "max_rounds": MAX_ROUNDS,
        "gate": {"path": gate.as_posix(), "sha256": hashlib.sha256(gate.read_bytes()).hexdigest()} if gate else None,
        "python": sys.version.split()[0],
        "run_started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def leakage_markers(task: RepoTask) -> list[str]:
    markers = [str(ORACLE_DIR), "oracle", "_oracle_hidden"]
    for path in resolve_hidden_tests(task):
        markers.append(path.name)
        markers.extend(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("assert "))
    return markers


# ------------------------------------------------------------------ fingerprint + checkpoint
def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not any(s in p.parts for s in _SKIP)):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def corpus_hash() -> str:
    manifest = hashlib.sha256((REPO_ROOT / "benchmark" / "repo_tasks.py").read_bytes()).hexdigest()
    return hashlib.sha256((_tree_hash(REPOS_DIR) + _tree_hash(ORACLE_DIR) + manifest).encode()).hexdigest()


def harness_hash() -> str:
    digest = hashlib.sha256()
    for rel in HARNESS_SOURCES:
        digest.update(rel.encode())
        digest.update((REPO_ROOT / rel).read_bytes())
    return digest.hexdigest()


def model_digest(model: str) -> str:
    models = requests.get(f"{OLLAMA}/api/tags", timeout=30).json().get("models", [])
    for entry in models:
        if entry.get("name") == model:
            return entry.get("digest", "")
    raise RuntimeError(f"model {model} is not installed in Ollama")


def task_fingerprint(task: RepoTask, condition: str, digest: str, corpus: str, harness: str) -> str:
    spec = asdict(task.public_spec)
    payload = {
        "task": task.name, "corpus": corpus, "harness": harness, "condition": condition, "model": CONDITIONS[condition]["model"],
        "model_digest": digest, "overrides": CONDITIONS[condition]["overrides"], "max_rounds": MAX_ROUNDS,
        "public_spec": spec,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.is_file() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# ------------------------------------------------------------------ residency evidence
RESIDENCY = REPO_ROOT / "benchmark" / "results" / "repo_task_eval_residency.jsonl"


def system_memory_mb() -> dict[str, float] | None:
    """Available/total physical RAM via the Windows API; None on other platforms."""
    if sys.platform != "win32":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return {"available_mb": round(status.ullAvailPhys / 2**20, 1), "total_mb": round(status.ullTotalPhys / 2**20, 1)}


def residency_snapshot(condition: str, phase: str) -> dict[str, Any]:
    try:
        loaded = [{"name": m.get("name"), "size_vram": m.get("size_vram"), "size": m.get("size")}
                  for m in requests.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])]
        ps_error = None
    except requests.RequestException as exc:
        loaded, ps_error = None, str(exc)
    return {"condition": condition, "phase": phase, "ts": time.time(), "ollama_loaded": loaded, "ollama_ps_error": ps_error,
            "ram": system_memory_mb(), "env_max_loaded_models": os.environ.get("OLLAMA_MAX_LOADED_MODELS"),
            "env_num_parallel": os.environ.get("OLLAMA_NUM_PARALLEL")}


# ------------------------------------------------------------------ memory contract
def unload_model(model: str, timeout: float = 60.0) -> bool:
    requests.post(f"{OLLAMA}/api/generate", json={"model": model, "keep_alive": 0}, timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        loaded = [m.get("name") for m in requests.get(f"{OLLAMA}/api/ps", timeout=10).json().get("models", [])]
        if model not in loaded:
            return True
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------ one task
def run_task(task: RepoTask, condition: str) -> dict[str, Any]:
    config = CONDITIONS[condition]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cordii-repo-task-") as tmp:
        workspace = seed_workspace(task, Path(tmp))
        seeded = repo_files(workspace)
        seed_texts = {rel: (workspace / rel).read_text(encoding="utf-8") for rel in seeded if (workspace / rel).suffix in (".py", ".json", ".txt", ".md")}
        ctx, reg = build_application(workspace, config["model"], OLLAMA, Path(tmp) / "eval.db", profile="lite", calibration_overrides=config["overrides"])
        model = ctx.plugins["ollama_model"]
        schema = getattr(model, "response_format", None)
        sent_texts: list[str] = []
        replies: list[str | None] = []
        reply_texts: list[str] = []
        prompt_tokens: list[int] = []
        original_chat = model.chat

        def recording_chat(messages, tools, _orig=original_chat, _model=model):
            sent_texts.extend(m.content or "" for m in messages)
            reply = _orig(messages, tools)
            reply_texts.append(((reply.content or "") + (f" [tool_calls] {json.dumps(reply.tool_calls, default=str)[:500]}" if reply.tool_calls else ""))[:1500])
            if tools and schema:
                replies.append(action_violation((reply.content or "").strip(), schema))
            usage = getattr(_model, "last_token_usage", None)
            if usage is not None:
                prompt_tokens.append(usage.prompt_eval_count)
            return reply

        model.chat = recording_chat
        timeline: list[tuple[str, dict[str, Any]]] = []
        ctx.events.on("*", lambda event: timeline.append((event.type, dict(event.payload or {}))))
        try:
            lane = run_bounded_task(task.public_spec, workspace, ctx.plugins["agent_loop"].run)
        finally:
            reg.stop_all()
        oracle = run_oracle(task, workspace)
        final_files = repo_files(workspace)
        damaged = damaged_files(workspace, seed_texts)
        diffs = write_diffs(workspace, seed_texts, seeded)
        calls, read_views = call_log(timeline, seed_texts)
        invalid = invalid_language_files(workspace, [normalize(g) for g in task.gold_files])
        diagnoses = diagnosis_records(timeline, task, seed_texts)
        markers = leakage_markers(task)
        leaked = sorted({m for m in markers if m and any(m in text for text in sent_texts)})
    model_claimed_done = lane.agent_escalation is None and not lane.reason.startswith("agent failed")
    solvable = task.expected_outcome == "verified_done"
    return {
        "task": task.name, "repo": task.repo, "split": task.split, "category": task.category, "condition": condition,
        "model": config["model"], "expected_outcome": task.expected_outcome,
        "lane_state": lane.state, "lane_reason": lane.reason[:500],
        "oracle_passed": oracle["passed"], "oracle_detail": oracle["detail"],
        "lane_false_verified": lane.state == "verified_done" and solvable and oracle["passed"] is False,
        "false_completion_on_insufficient_evidence": (not solvable) and lane.state == "verified_done",
        "model_claimed_done": model_claimed_done,
        "model_false_done_claim": model_claimed_done and not (solvable and oracle["passed"]),
        "agent_escalation": (lane.agent_escalation or {}).get("reason"),
        **localization_metrics(timeline, task.gold_files),
        "damaged_files": damaged,
        "stray_files": sorted(final_files - seeded - set(task.public_spec.mutable_paths)),
        "guard_rejections": rejection_outcomes(timeline),
        "calls": calls,
        "read_views": read_views,
        "write_diffs": diffs,
        "model_outputs": reply_texts,
        "truncated_read_views": sum(1 for v in read_views if v["complete"] is False),
        "gold_shown_complete": all(g in {v["path"] for v in read_views if v["complete"] is True} for g in (normalize(x) for x in task.gold_files)),
        "diagnoses": diagnoses,
        "invalid_gold_files": invalid,
        "failure_split": failure_split(task, condition, oracle["passed"], read_views, diagnoses, diffs, damaged, invalid),
        "invalid_actions": [v for v in replies if v is not None],
        "model_replies": len(replies),
        "rounds": sum(1 for t, _ in timeline if t == "turn.round"),
        "tool_calls": sum(1 for t, _ in timeline if t == "tool.invoked"),
        "prompt_tokens": sum(prompt_tokens),
        "leaked_markers": leaked,
        "completion_checks": [{k: p.get(k) for k in ("round", "reason", "latch_version", "mutation_version", "action")}
                              for t, p in timeline if t == "completion.latch"],
        "seconds": round(time.perf_counter() - started, 1),
    }


# ------------------------------------------------------------------ summary
def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}"


def summarize_condition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    solvable = [r for r in rows if r["expected_outcome"] == "verified_done"]
    insufficient = [r for r in rows if r["expected_outcome"] == "escalate"]

    def mean(key: str, subset: list[dict[str, Any]]) -> float | None:
        values = [r[key] for r in subset if r.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "tasks": len(rows),
        "verified_done_solvable": _rate(sum(r["lane_state"] == "verified_done" for r in solvable), len(solvable)),
        "oracle_passed_solvable": _rate(sum(bool(r["oracle_passed"]) for r in solvable), len(solvable)),
        "lane_false_verified": sum(r["lane_false_verified"] for r in rows),
        "false_completion_on_insufficient_evidence": _rate(sum(r["false_completion_on_insufficient_evidence"] for r in insufficient), len(insufficient)),
        "model_false_done_claims": sum(r["model_false_done_claim"] for r in rows),
        "read_recall": mean("read_recall", solvable),
        "read_precision": mean("read_precision", solvable),
        "mutation_precision": mean("mutation_precision", solvable),
        "gold_first_touch": _rate(sum(bool(r["gold_first_touch"]) for r in solvable), len(solvable)),
        "gold_edit_recall": mean("gold_edit_recall", solvable),
        "damaged_file_tasks": sum(bool(r["damaged_files"]) for r in rows),
        "stray_file_tasks": sum(bool(r["stray_files"]) for r in rows),
        "agent_escalations": sum(r["agent_escalation"] is not None for r in rows),
        "invalid_actions": sum(len(r["invalid_actions"]) for r in rows),
        "rounds": sum(r["rounds"] for r in rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "leaks": sum(bool(r["leaked_markers"]) for r in rows),
        "seconds": round(sum(r["seconds"] for r in rows), 1),
        **diagnose_gate_metrics(solvable),
    }


def diagnose_gate_metrics(solvable: list[dict[str, Any]]) -> dict[str, Any]:
    """Gate diagnose_v1 fields. Rows from before this instrumentation lack them and are reported as None."""
    if not solvable or any("truncated_read_views" not in r for r in solvable):
        return {"invalid_solvable_rows": None}
    valid = [r for r in solvable if r["truncated_read_views"] == 0]
    splits: dict[str, int] = {}
    for r in valid:
        if r["failure_split"]:
            splits[r["failure_split"]] = splits.get(r["failure_split"], 0) + 1
    return {
        "invalid_solvable_rows": len(solvable) - len(valid),
        "oracle_passed_valid_solvable": _rate(sum(bool(r["oracle_passed"]) for r in valid), len(valid)),
        "gold_shown_complete": _rate(sum(r["gold_shown_complete"] for r in valid), len(valid)),
        "tasks_with_successful_diagnosis": _rate(sum(any(d["success"] for d in r["diagnoses"]) for r in valid), len(valid)),
        "tasks_with_defect_hit": _rate(sum(any(d["hits_defect"] for d in r["diagnoses"]) for r in valid), len(valid)),
        "tasks_with_localized_hit": _rate(sum(any(d.get("hits_defect_localized") for d in r["diagnoses"]) for r in valid), len(valid)),
        "diagnose_attempts": sum(len(r["diagnoses"]) for r in valid),
        "diagnose_refused_pre_read": sum(1 for r in valid for d in r["diagnoses"] if d.get("refused") == "evidence_requires_read"),
        "diagnose_executed_pre_read": sum(1 for r in valid for d in r["diagnoses"] if d.get("refused") is None and d.get("pre_read")),
        "diagnose_executed_valid": _rate(sum(1 for r in valid for d in r["diagnoses"] if d["success"]),
                                         sum(1 for r in valid for d in r["diagnoses"] if d.get("refused") is None)),
        "diagnosis_required_rejections": sum(1 for r in valid for g in r["guard_rejections"] if g.get("reason") == "diagnosis_required"),
        "failure_split": splits,
    }


def current_rows(results: Path, split: str, condition: str, fingerprints: dict[str, str]) -> list[dict[str, Any]]:
    by_task = {}
    for row in load_rows(results):
        if row.get("condition") == condition and row.get("split") == split and fingerprints.get(row.get("task")) == row.get("fingerprint"):
            by_task[row["task"]] = row
    return list(by_task.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Repository task eval with independent hidden-test oracle")
    parser.add_argument("--condition", choices=[*CONDITIONS, "all"], default="all")
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--task", action="append", help="Only run the named task(s)")
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--max-new", type=int, default=None, help="Stop after this many new task runs (resume by re-running)")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--gate", type=Path, default=None, help="Pre-registered gate file; its sha256 is stored on every new row")
    args = parser.parse_args()
    if args.gate is not None and not args.gate.is_file():
        parser.error(f"gate file not found: {args.gate}")

    results = Path(args.results)
    tasks = [t for t in TASKS if t.split == args.split and (not args.task or t.name in args.task)]
    conditions = list(CONDITIONS) if args.condition == "all" else [args.condition]
    corpus = corpus_hash()
    harness = harness_hash()
    budget = args.max_new
    summary: dict[str, Any] = {}
    for condition in conditions:
        model = CONDITIONS[condition]["model"]
        digest = model_digest(model)
        fingerprints = {t.name: task_fingerprint(t, condition, digest, corpus, harness) for t in tasks}
        done = {r["task"] for r in current_rows(results, args.split, condition, fingerprints)}
        pending = [t for t in tasks if t.name not in done]
        if not args.summary_only:
            append_row(RESIDENCY, residency_snapshot(condition, "before"))
            for task in pending:
                if budget is not None and budget <= 0:
                    break
                row = run_task(task, condition)
                row["fingerprint"] = fingerprints[task.name]
                row["experiment"] = experiment_identity(condition, digest, corpus, harness, args.gate)
                append_row(results, row)
                print(json.dumps({k: row[k] for k in ("condition", "task", "lane_state", "oracle_passed", "lane_false_verified", "leaked_markers", "seconds")}), flush=True)
                if budget is not None:
                    budget -= 1
            append_row(RESIDENCY, residency_snapshot(condition, "after_run"))
            released = unload_model(model)
            append_row(RESIDENCY, {**residency_snapshot(condition, "after_unload"), "model_unloaded": released})
            print(json.dumps({"condition": condition, "model_unloaded": released}), flush=True)
        rows = current_rows(results, args.split, condition, fingerprints)
        summary[condition] = {"complete": len(rows) == len(tasks), **summarize_condition(rows)}
    print(json.dumps({"split": args.split, "corpus": corpus[:12], "harness": harness[:12], "conditions": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
