from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.bounded_task as bounded
from benchmark import repo_task_eval as rte
from benchmark.repo_tasks import TASKS_BY_NAME
from core.bounded_task import CheckResult


def test_l1_conditions_add_only_grounding():
    for model in ("gemma", "qwen"):
        base, l1 = rte.CONDITIONS[f"{model}_constrained"], rte.CONDITIONS[f"{model}_L1"]
        assert base["model"] == l1["model"]
        assert l1["overrides"] == {**base["overrides"], "targeted_grounding": True}
        assert "targeted_grounding" not in base["overrides"] and "evidence_gated_completion" not in l1["overrides"]


def test_conditions_differ_only_in_the_named_factor():
    gemma, qwen_c, qwen_n = (rte.CONDITIONS[k] for k in ("gemma_constrained", "qwen_constrained", "qwen_native"))
    assert gemma["overrides"] == qwen_c["overrides"] and gemma["model"] != qwen_c["model"]
    assert qwen_c["model"] == qwen_n["model"]
    differing = {k for k in qwen_c["overrides"] if qwen_c["overrides"][k] != qwen_n["overrides"].get(k)}
    assert differing == {"constrained_actions", "text_tool_protocol"}


def test_oracle_catches_a_verifier_that_always_passes(tmp_path, monkeypatch):
    task = TASKS_BY_NAME["mathlib_fix_subtract"]
    workspace = rte.seed_workspace(task, tmp_path)
    monkeypatch.setattr(bounded, "run_check", lambda check, ws, before: CheckResult(check, True, "mutated verifier"))

    def wrong_fix(_instruction):
        path = workspace / "mathlib" / "operations.py"
        path.write_text(path.read_text(encoding="utf-8").replace("return b - a", "return 0"), encoding="utf-8")
        return "Task completed successfully."

    lane = bounded.run_bounded_task(task.public_spec, workspace, wrong_fix)
    oracle = rte.run_oracle(task, workspace)
    assert lane.state == "verified_done"
    assert oracle["passed"] is False
    assert lane.state == "verified_done" and oracle["passed"] is False  # = lane_false_verified in run_task


def test_oracle_does_not_modify_workspace(tmp_path):
    task = TASKS_BY_NAME["inventory_update_qty"]
    workspace = rte.seed_workspace(task, tmp_path)
    before = rte.repo_files(workspace)
    rte.run_oracle(task, workspace)
    assert rte.repo_files(workspace) == before
    assert not list(workspace.rglob("_oracle_hidden"))


def test_insufficient_evidence_task_has_no_oracle(tmp_path):
    task = TASKS_BY_NAME["config_database_password"]
    assert rte.run_oracle(task, rte.seed_workspace(task, tmp_path))["applicable"] is False


def _result(tool, path, success=True):
    return ("tool.result", {"tool": tool, "arguments": {"path": path}, "success": success})


def test_localization_precision_penalizes_reading_everything():
    gold = ("mathlib/operations.py",)
    focused = [_result("read_file", "mathlib/operations.py"), _result("write_file", "mathlib/operations.py")]
    shotgun = [_result("read_file", p) for p in ("calculator.py", "legacy/operations.py", "mathlib/stats.py", "mathlib/operations.py")] + [_result("write_file", "legacy/operations.py")]
    f = rte.localization_metrics(focused, gold)
    s = rte.localization_metrics(shotgun, gold)
    assert (f["read_recall"], f["read_precision"], f["mutation_precision"], f["gold_first_touch"], f["first_gold_rank"], f["gold_edit_recall"]) == (1.0, 1.0, 1.0, True, 0, 1.0)
    assert (s["read_recall"], s["read_precision"], s["mutation_precision"], s["gold_first_touch"], s["first_gold_rank"], s["gold_edit_recall"]) == (1.0, 0.25, 0.0, False, 3, 0.0)
    assert rte.localization_metrics([_result("read_file", "x.py", success=False)], gold)["read_precision"] is None


def test_leakage_markers_cover_hidden_names_and_asserts_but_not_public_spec():
    from dataclasses import asdict

    task = TASKS_BY_NAME["config_service_port"]
    markers = rte.leakage_markers(task)
    assert "test_config_service_port.py" in markers
    assert any(m.startswith("assert ") for m in markers)
    public = json.dumps(asdict(task.public_spec)) + task.prompt
    assert not [m for m in markers if m in public]


def test_fingerprint_changes_with_every_factor(monkeypatch):
    task = TASKS_BY_NAME["mathlib_fix_subtract"]
    base = rte.task_fingerprint(task, "gemma_constrained", "digest-a", "corpus-a", "harness-a")
    assert base == rte.task_fingerprint(task, "gemma_constrained", "digest-a", "corpus-a", "harness-a")
    assert base != rte.task_fingerprint(task, "qwen_constrained", "digest-a", "corpus-a", "harness-a")
    assert base != rte.task_fingerprint(task, "gemma_constrained", "digest-b", "corpus-a", "harness-a")
    assert base != rte.task_fingerprint(task, "gemma_constrained", "digest-a", "corpus-b", "harness-a")
    assert base != rte.task_fingerprint(task, "gemma_constrained", "digest-a", "corpus-a", "harness-b")
    changed = dict(rte.CONDITIONS["gemma_constrained"], overrides={**rte.CONDITIONS["gemma_constrained"]["overrides"], "repeat_retry_temperature": 0.5})
    monkeypatch.setitem(rte.CONDITIONS, "gemma_constrained", changed)
    assert base != rte.task_fingerprint(task, "gemma_constrained", "digest-a", "corpus-a", "harness-a")


def test_append_row_fsyncs_and_recovers_partial_line(tmp_path, monkeypatch):
    synced = []
    real_fsync = rte.os.fsync
    monkeypatch.setattr(rte.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))
    path = tmp_path / "rows.jsonl"
    rte.append_row(path, {"task": "a"})
    path.write_bytes(path.read_bytes() + b'{"task": "partial')
    rte.append_row(path, {"task": "b"})
    assert [r["task"] for r in rte.load_rows(path)] == ["a", "b"]
    assert len(synced) == 2


def test_residency_snapshot_records_loaded_models_and_ram(monkeypatch):
    class Response:
        def json(self):
            return {"models": [{"name": "gemma3:1b", "size": 1, "size_vram": 0}]}

    monkeypatch.setattr(rte.requests, "get", lambda url, timeout: Response())
    snap = rte.residency_snapshot("gemma_constrained", "before")
    assert snap["ollama_loaded"] == [{"name": "gemma3:1b", "size_vram": 0, "size": 1}]
    assert snap["phase"] == "before" and snap["ollama_ps_error"] is None
    if rte.sys.platform == "win32":
        assert snap["ram"]["total_mb"] > snap["ram"]["available_mb"] > 0

    def down(url, timeout):
        raise rte.requests.ConnectionError("refused")

    monkeypatch.setattr(rte.requests, "get", down)
    failed = rte.residency_snapshot("gemma_constrained", "after_unload")
    assert failed["ollama_loaded"] is None and "refused" in failed["ollama_ps_error"]


def test_call_log_records_calls_and_how_much_of_each_read_was_shown():
    seed = {"a.py": "x" * 250, "b.py": "short"}
    timeline = [
        ("turn.round", {}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "a.py"}, "success": True, "result": "x" * 200 + "..."}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "./b.py"}, "success": True, "result": "short"}),
        ("turn.round", {}),
        ("tool.result", {"tool": "write_file", "arguments": {"path": "b.py", "content": "y" * 400}, "success": True, "result": "ok"}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "b.py"}, "success": True, "result": "y" * 400}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "ghost.py"}, "success": False, "result": "not found"}),
        ("tool.result", {"tool_name": "zero_token_tool", "arguments": {}, "success": True, "result": "ignored"}),
    ]
    calls, views = rte.call_log(timeline, seed)
    assert [(c["round"], c["tool"], c["success"]) for c in calls] == [(1, "read_file", True), (1, "read_file", True), (2, "write_file", True), (2, "read_file", True), (2, "read_file", False)]
    assert calls[2]["args"]["content"]["chars"] == 400 and len(calls[2]["args"]["content"]["head"]) == 300
    assert views == [
        {"round": 1, "path": "a.py", "file_chars": 250, "shown_chars": 203, "complete": False},
        {"round": 1, "path": "b.py", "file_chars": 5, "shown_chars": 5, "complete": True},
        {"round": 2, "path": "b.py", "file_chars": None, "shown_chars": 400, "complete": None},
    ]


def test_write_diffs_changed_created_deleted(tmp_path):
    for rel, text in {"keep.py": "a\n", "edit.py": "return b - a\n", "gone.json": "{}"}.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    seeded = rte.repo_files(tmp_path)
    seed_texts = {rel: (tmp_path / rel).read_text(encoding="utf-8") for rel in seeded}
    (tmp_path / "edit.py").write_text("return a - b\n", encoding="utf-8")
    (tmp_path / "gone.json").unlink()
    (tmp_path / "new.txt").write_text("hello", encoding="utf-8")
    diffs = rte.write_diffs(tmp_path, seed_texts, seeded)
    assert set(diffs) == {"edit.py", "gone.json", "new.txt"}
    assert "-return b - a" in diffs["edit.py"]["diff"] and "+return a - b" in diffs["edit.py"]["diff"]
    assert diffs["gone.json"] == {"deleted": True}
    assert diffs["new.txt"] == {"created": True, "chars": 5, "head": "hello"}


def test_experiment_identity_records_gate_hash_outside_fingerprint(tmp_path):
    gate = tmp_path / "gate.md"
    gate.write_text("oracle +3", encoding="utf-8")
    ident = rte.experiment_identity("gemma_L1", "digest", "corpus", "harness", gate)
    assert ident["gate"]["sha256"] == __import__("hashlib").sha256(b"oracle +3").hexdigest()
    assert (ident["model"], ident["model_digest"], ident["corpus_sha256"], ident["harness_sha256"]) == ("gemma3:1b", "digest", "corpus", "harness")
    assert ident["overrides_sha256"] != rte.experiment_identity("gemma_constrained", "digest", "corpus", "harness", None)["overrides_sha256"]
    assert rte.experiment_identity("gemma_L1", "digest", "corpus", "harness", None)["gate"] is None
    task = TASKS_BY_NAME["mathlib_fix_subtract"]
    assert "gate" not in __import__("inspect").signature(rte.task_fingerprint).parameters
    assert rte.task_fingerprint(task, "gemma_L1", "d", "c", "h") == rte.task_fingerprint(task, "gemma_L1", "d", "c", "h")


def test_run_task_rows_carry_calls_read_views_diffs_and_model_outputs(monkeypatch):
    """Real run_task path (production build_application, lane, oracle) with only the model's chat scripted."""
    from core.messages import Message

    script = [
        '{"tool": "read", "args": {"path": "inventory/service.py"}}',
        '{"tool": "write", "args": {"path": "notes.txt", "content": "total_value ignores qty"}}',
        '{"tool": "done", "args": {"summary": "noted"}}',
    ]
    real_build = rte.build_application

    def scripted_build(*args, **kwargs):
        ctx, reg = real_build(*args, **kwargs)
        model = ctx.plugins["ollama_model"]
        model.chat = lambda messages, tools: Message("assistant", script.pop(0))
        model.last_done_reason = "stop"
        return ctx, reg

    monkeypatch.setattr(rte, "build_application", scripted_build)
    row = rte.run_task(TASKS_BY_NAME["inventory_total_value"], "gemma_L1")
    assert [c["tool"] for c in row["calls"]] == ["read_file", "write_file"]
    assert row["read_views"][0]["path"] == "inventory/service.py" and row["read_views"][0]["complete"] is False
    assert row["read_views"][0]["file_chars"] == 277 and row["read_views"][0]["shown_chars"] < 277
    assert row["write_diffs"] == {"notes.txt": {"created": True, "chars": 23, "head": "total_value ignores qty"}}
    assert row["model_outputs"][0].startswith('{"tool": "read"') and len(row["model_outputs"]) == 3
    assert row["oracle_passed"] is False and row["lane_state"] == "escalate"


def test_diagnose_arms_differ_only_in_the_diagnosis_flag():
    for model in ("gemma", "qwen"):
        control, treat = rte.CONDITIONS[f"{model}_fullread"], rte.CONDITIONS[f"{model}_diagnose"]
        assert control["model"] == treat["model"] == rte.CONDITIONS[f"{model}_L1"]["model"]
        assert control["overrides"] == {**rte.CONDITIONS[f"{model}_L1"]["overrides"], "full_read_views": True}
        assert treat["overrides"] == {**control["overrides"], "diagnose_before_mutation": True}
    for source in ("core/grounding.py", "core/diagnosis.py", "core/repo_index.py"):
        assert source in rte.HARNESS_SOURCES


def test_defect_lines_and_diagnosis_hits_use_the_reference_patch():
    task = TASKS_BY_NAME["inventory_total_value"]
    seed = (rte.REPOS_DIR / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
    assert rte.defect_lines(seed, task.reference_patch["inventory/service.py"]) == {5}
    assert rte.defect_lines("a\nb\n", "a\nnew\nb\n") == {1, 2}

    def diag(evidence, success=True, path="inventory/service.py"):
        return ("tool.result", {"tool": "diagnose", "arguments": {"path": path, "evidence": evidence}, "success": success})

    timeline = [diag("return sum(item.price for item in items)"), diag("def low_stock(items, threshold):"),
                diag("return sum(item.price for item in items)", success=False), diag("REORDER_THRESHOLD = 10", path="inventory/__init__.py")]
    records = rte.diagnosis_records(timeline, task, {"inventory/service.py": seed, "inventory/__init__.py": "x"})
    assert [(r["seed_span"], r["hits_defect"]) for r in records] == [([5, 5], True), ([8, 8], False), ([5, 5], False), (None, False)]


def test_failure_split_branches():
    task = TASKS_BY_NAME["inventory_total_value"]
    full = [{"path": "inventory/service.py", "complete": True}]
    hit = [{"hits_defect": True}]
    diff = {"inventory/service.py": {"diff": "-x\n+y"}}
    split = lambda cond, **kw: rte.failure_split(task, cond, kw.get("oracle", False), kw.get("views", full), kw.get("diags", hit),
                                                 kw.get("diffs", diff), kw.get("damaged", []), kw.get("invalid", []))
    assert split("gemma_diagnose", oracle=True) is None
    assert split("gemma_diagnose", views=[{"path": "inventory/service.py", "complete": False}]) == "no_gold_view"
    assert split("gemma_fullread") == "gold_viewed_failed"
    assert split("gemma_diagnose", diags=[{"hits_defect": False}]) == "gold_viewed_no_diagnosis_hit"
    assert split("gemma_diagnose", diffs={}) == "mechanical_failure"
    assert split("gemma_diagnose", invalid=["inventory/service.py"]) == "mechanical_failure"
    assert split("gemma_diagnose", damaged=["inventory/service.py"]) == "mechanical_failure"
    assert split("gemma_diagnose") == "wrong_edit_choice"
    assert rte.failure_split(TASKS_BY_NAME["config_database_password"], "gemma_diagnose", None, [], [], {}, [], []) is None


def _scripted_run(monkeypatch, task_name, condition, script):
    from core.messages import Message

    real_build = rte.build_application

    def scripted_build(*args, **kwargs):
        ctx, reg = real_build(*args, **kwargs)
        model = ctx.plugins["ollama_model"]
        model.chat = lambda messages, tools: Message("assistant", script.pop(0))
        model.last_done_reason = "stop"
        return ctx, reg

    monkeypatch.setattr(rte, "build_application", scripted_build)
    return rte.run_task(TASKS_BY_NAME[task_name], condition)


def test_diagnose_arm_end_to_end_correct_and_wrong_fix(monkeypatch):
    task = TASKS_BY_NAME["inventory_total_value"]
    fixed = task.reference_patch["inventory/service.py"]
    wrong = fixed.replace("item.qty * item.price", "item.qty + item.price")
    read = '{"tool": "read", "args": {"path": "inventory/service.py"}}'
    diagnose = json.dumps({"tool": "diagnose", "args": {"path": "inventory/service.py", "evidence": "return sum(item.price for item in items)", "cause": "ignores qty", "change": "multiply by qty"}})
    done = '{"tool": "done", "args": {"summary": "fixed"}}'

    row = _scripted_run(monkeypatch, "inventory_total_value", "gemma_diagnose",
                        [read, json.dumps({"tool": "write", "args": {"path": "inventory/service.py", "content": fixed}}), diagnose,
                         json.dumps({"tool": "write", "args": {"path": "inventory/service.py", "content": fixed}}), done])
    assert row["truncated_read_views"] == 0 and row["gold_shown_complete"] is True
    assert [g["reason"] for g in row["guard_rejections"]] == ["diagnosis_required"]
    assert row["diagnoses"][0]["hits_defect"] is True
    assert row["lane_state"] == "verified_done" and row["oracle_passed"] is True and row["lane_false_verified"] is False
    assert row["failure_split"] is None

    row = _scripted_run(monkeypatch, "inventory_total_value", "gemma_diagnose",
                        [read, diagnose, json.dumps({"tool": "write", "args": {"path": "inventory/service.py", "content": wrong}}), done])
    assert row["oracle_passed"] is False and row["failure_split"] == "wrong_edit_choice"

    row = _scripted_run(monkeypatch, "inventory_total_value", "gemma_L1", [read, done])
    assert row["truncated_read_views"] == 1 and row["gold_shown_complete"] is False and row["failure_split"] == "no_gold_view"


def test_diagnose_gate_metrics_exclude_rows_with_truncated_reads():
    base = {"expected_outcome": "verified_done", "guard_rejections": [], "diagnoses": [], "gold_shown_complete": True}
    rows = [
        {**base, "truncated_read_views": 0, "oracle_passed": True, "failure_split": None, "diagnoses": [{"success": True, "hits_defect": True}]},
        {**base, "truncated_read_views": 0, "oracle_passed": False, "failure_split": "wrong_edit_choice", "guard_rejections": [{"reason": "diagnosis_required"}]},
        {**base, "truncated_read_views": 2, "oracle_passed": True, "failure_split": None},
    ]
    m = rte.diagnose_gate_metrics(rows)
    assert m["invalid_solvable_rows"] == 1 and m["oracle_passed_valid_solvable"] == "1/2"
    assert (m["tasks_with_successful_diagnosis"], m["tasks_with_defect_hit"], m["diagnosis_required_rejections"]) == ("1/2", "1/2", 1)
    assert m["failure_split"] == {"wrong_edit_choice": 1}
    assert rte.diagnose_gate_metrics([{"expected_outcome": "verified_done"}]) == {"invalid_solvable_rows": None}


def test_progress_arm_differs_only_in_progress_recovery():
    control, treat = rte.CONDITIONS["gemma_fullread"], rte.CONDITIONS["gemma_progress"]
    assert control["model"] == treat["model"] == "gemma3:1b"
    assert treat["overrides"] == {**control["overrides"], "progress_recovery": True}


def test_progress_metrics_frozen_definitions():
    task = TASKS_BY_NAME["inventory_total_value"]
    files = {"inventory/service.py", "inventory/__init__.py"}
    out = lambda tool, **args: json.dumps({"tool": tool, "args": args}) + " [tool_calls] []"
    call = lambda tool, path, success, **extra: {"tool": tool, "args": {"path": path}, "success": success, **extra}
    row = {
        "model_outputs": [out("read", path="service.py"), out("read", path="service.py"), out("read", path="inventory/service.py"),
                          out("read", path="inventory/service.py"), out("write", path="inventory/service.py", content="x"), "not json"],
        "calls": [call("read_file", "service.py", False), call("read_file", "service.py", False, recovery="repeated_missing_path"),
                  call("read_file", "inventory/service.py", True),
                  call("read_file", "inventory/service.py", False, recovery="repeated_successful_read"),
                  call("write_file", "inventory/service.py", False)],
    }
    m = rte.progress_metrics(row, task, files)
    assert (m["edit_opportunity"], m["reread_loop"], m["missing_read_loop"], m["executed_edit"]) == (True, True, True, False)
    assert (m["successful_read_followed_by_same"], m["read_proposals_existing_successful"]) == (1, 2)
    assert (m["missing_read_followed_by_same"], m["read_proposals_missing"]) == (1, 2)
    assert m["recoveries"] == {"repeated_successful_read": 1, "repeated_missing_path": 1}

    no_read_first = {"model_outputs": [out("write", path="inventory/service.py", content="x")], "calls": [call("write_file", "inventory/service.py", False)]}
    assert rte.progress_metrics(no_read_first, task, files)["edit_opportunity"] is False
    insufficient = TASKS_BY_NAME["config_database_password"]
    assert rte.progress_metrics({"model_outputs": [], "calls": []}, insufficient, set())["edit_opportunity"] is None


def test_evidence_arm_differs_only_in_read_before_evidence():
    control, treat = rte.CONDITIONS["qwen_diagnose"], rte.CONDITIONS["qwen_evidence"]
    assert control["model"] == treat["model"] == "qwen2.5-coder:1.5b"
    assert treat["overrides"] == {**control["overrides"], "read_before_evidence": True}


def test_localization_cap_and_pre_read_flags():
    task = TASKS_BY_NAME["inventory_total_value"]
    seed = (rte.REPOS_DIR / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
    assert rte.localization_cap(seed) == 3 and rte.localization_cap("\n".join(["x"] * 40)) == 10

    def diag(evidence, success=True):
        return ("tool.result", {"tool": "diagnose", "arguments": {"path": "inventory/service.py", "evidence": evidence}, "success": success})

    read = ("tool.result", {"tool": "read_file", "arguments": {"path": "inventory/service.py"}, "success": True})
    refused = ("guard.rejected", {"tool": "diagnose", "path": "inventory/service.py", "reason": "evidence_requires_read"})
    whole = seed.strip()
    loop_echo = diag("", success=False)  # the loop's own failed tool.result after a guard rejection: must not be double-counted
    records = rte.diagnosis_records([refused, loop_echo, diag(whole), read, diag("return sum(item.price for item in items)")], task, {"inventory/service.py": seed})
    assert [(r["refused"], r["pre_read"], r["localized"], r["hits_defect"], r["hits_defect_localized"]) for r in records] == [
        ("evidence_requires_read", True, False, False, False),
        (None, True, False, True, False),   # whole-file quote: hits but not localized
        (None, False, True, True, True),
    ]
    metrics = rte.diagnose_gate_metrics([{"expected_outcome": "verified_done", "truncated_read_views": 0, "oracle_passed": False, "failure_split": None,
                                          "guard_rejections": [], "gold_shown_complete": True, "diagnoses": records}])
    assert (metrics["tasks_with_defect_hit"], metrics["tasks_with_localized_hit"]) == ("1/1", "1/1")
    assert (metrics["diagnose_attempts"], metrics["diagnose_refused_pre_read"], metrics["diagnose_executed_pre_read"], metrics["diagnose_executed_valid"]) == (3, 1, 1, "2/2")


def test_extract_arm_differs_only_in_evidence_extraction():
    control, treat = rte.CONDITIONS["qwen_evidence"], rte.CONDITIONS["qwen_extract"]
    assert control["model"] == treat["model"] == "qwen2.5-coder:1.5b"
    assert treat["overrides"] == {**control["overrides"], "evidence_extraction": True}


def test_diagnosis_records_for_selector_diagnoses():
    import hashlib

    task = TASKS_BY_NAME["inventory_total_value"]
    seed = (rte.REPOS_DIR / "inventory" / "inventory" / "service.py").read_text(encoding="utf-8")
    seed_sha = hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def diag(target, sha, success=True):
        return ("tool.result", {"tool": "diagnose", "arguments": {"path": "inventory/service.py", "target": target},
                                "success": success, "result": f"Diagnosis recorded ...\nsnapshot_sha256: {sha}"})

    read = ("tool.result", {"tool": "read_file", "arguments": {"path": "inventory/service.py"}, "success": True})
    records = rte.diagnosis_records([read, diag("total_value", seed_sha), diag("low_stock", seed_sha), diag("total_value", "0" * 64),
                                     diag("nope", seed_sha, success=False)], task, {"inventory/service.py": seed})
    assert [(r["target"], r["seed_span"], r["snapshot_matches_seed"], r["localized"], r["hits_defect_localized"]) for r in records] == [
        ("total_value", [4, 5], True, True, True),
        ("low_stock", [8, 9], True, True, False),
        ("total_value", None, False, False, False),  # snapshot differs from seed: hit undetermined, not counted
        ("nope", None, True, False, False),
    ]


def test_current_rows_ignores_stale_fingerprints(tmp_path):
    path = tmp_path / "rows.jsonl"
    rte.append_row(path, {"task": "t1", "condition": "gemma_constrained", "split": "dev", "fingerprint": "old"})
    rte.append_row(path, {"task": "t1", "condition": "gemma_constrained", "split": "dev", "fingerprint": "new"})
    rows = rte.current_rows(path, "dev", "gemma_constrained", {"t1": "new"})
    assert [r["fingerprint"] for r in rows] == ["new"]
    assert rte.current_rows(path, "dev", "gemma_constrained", {"t1": "other"}) == []
