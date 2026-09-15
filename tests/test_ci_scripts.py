"""CI support scripts: frozen-artifact verification (read-only) and the pytest known-failure gate."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_pytest_gate as gate  # noqa: E402
import verify_frozen_artifacts as vfa  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_repo(tmp_path: Path) -> Path:
    files = {
        "benchmark/gates/g_v1.md": b"gate text\r\n",
        "benchmark/scoring/g_v1.py": b"print('scorer')\n",
        "benchmark/repos/r/a.py": b"x = 1\n",
        "benchmark/oracle/r/hidden/test_a.py": b"assert True\n",
        "benchmark/repo_tasks.py": b"TASKS = []\n",
    }
    for rel, data in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    results = tmp_path / "benchmark" / "results"
    results.mkdir(parents=True, exist_ok=True)
    stdout = {"gate": {"path": "benchmark/gates/g_v1.md", "sha256": sha(files["benchmark/gates/g_v1.md"])},
              "scorer": {"path": "benchmark/scoring/g_v1.py", "sha256": sha(files["benchmark/scoring/g_v1.py"])},
              "verdict": {"result": "PASS"}}
    (results / "g_v1_scorer_stdout.txt").write_bytes(b"\xef\xbb\xbf" + json.dumps(stdout).encode() + b"\r\n")
    (results / "g_v1_frozen.json").write_text(json.dumps({"verdict": {"result": "PASS"}}), encoding="utf-8")
    rows = [{"condition": "c", "split": "dev", "task": "t1", "fingerprint": "f1"}, {"condition": "c", "split": "dev", "task": "t2", "fingerprint": "f2"}]
    (results / "repo_task_eval.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    log = (f"- Gate `benchmark/gates/g_v1.md` sha256 `{'0' * 64}` (superseded draft)\n"
           f"- Gate `benchmark/gates/g_v1.md` sha256 `{sha(files['benchmark/gates/g_v1.md'])}`\n"
           f"- Scorer `scratch/never_committed.py` sha256 `{'1' * 64}`\n")
    (tmp_path / "EXPERIMENT_LOG.md").write_text(log, encoding="utf-8")
    vfa.main(["--root", str(tmp_path), "--write-manifest"])
    return tmp_path


def test_clean_fixture_passes_every_check(tmp_path):
    root = make_repo(tmp_path)
    assert vfa.main(["--root", str(root)]) == 0


def test_manifest_detects_modified_missing_and_unrecorded_files(tmp_path):
    root = make_repo(tmp_path)
    (root / "benchmark/repos/r/a.py").write_bytes(b"x = 2\n")
    (root / "benchmark/oracle/r/hidden/test_a.py").unlink()
    (root / "benchmark/results/new.json").write_text("{}", encoding="utf-8")
    errors = vfa.check_manifest(root)
    assert any("a.py sha256" in e for e in errors)
    assert any("test_a.py is recorded but missing" in e for e in errors)
    assert any("new.json exists but is not recorded" in e for e in errors)


def test_line_ending_change_breaks_the_manifest(tmp_path):
    root = make_repo(tmp_path)
    (root / "benchmark/gates/g_v1.md").write_bytes(b"gate text\n")
    assert any("g_v1.md sha256" in e for e in vfa.check_manifest(root))


def test_logged_hashes_use_the_last_record_and_skip_uncommitted_paths(tmp_path):
    root = make_repo(tmp_path)
    errors, checked = vfa.check_logged(root)
    assert errors == [] and checked == 1
    with (root / "EXPERIMENT_LOG.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- Gate `benchmark/gates/g_v1.md` sha256 `{'2' * 64}`\n")
    errors, _ = vfa.check_logged(root)
    assert errors and "last logged 222222222222" in errors[0]


def test_scorer_output_checks_never_execute_and_detect_mismatches(tmp_path):
    root = make_repo(tmp_path)
    errors, checked = vfa.check_scorer_outputs(root)
    assert errors == [] and checked == 1
    (root / "benchmark/results/g_v1_frozen.json").write_text(json.dumps({"verdict": {"result": "FAIL"}}), encoding="utf-8")
    (root / "benchmark/scoring/g_v1.py").write_bytes(b"raise SystemExit('scorer must never run')\n")
    errors, _ = vfa.check_scorer_outputs(root)
    assert any("verdict 'PASS' != g_v1_frozen.json 'FAIL'" in e for e in errors)
    assert any("recorded scorer sha256 does not match" in e for e in errors)


def test_rows_detect_duplicates_missing_keys_and_bad_json(tmp_path):
    root = make_repo(tmp_path)
    with (root / "benchmark/results/repo_task_eval.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"condition": "c", "split": "dev", "task": "t1", "fingerprint": "f1"}) + "\n")
        handle.write(json.dumps({"condition": "c", "split": "dev", "task": "t3"}) + "\n")
        handle.write("{not json\n")
    errors, count = vfa.check_rows(root)
    assert count == 5
    assert any("duplicates" in e for e in errors) and any("missing fingerprint" in e for e in errors) and any("not valid JSON" in e for e in errors)


def junit(tmp_path: Path, cases: str) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>', encoding="utf-8")
    return path


def test_pytest_gate_allows_only_known_environment_failures(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_run_command.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("", encoding="utf-8")
    known = ('<testcase classname="tests.test_run_command" name="test_run_command_timeout"><failure message="x"/></testcase>'
             '<testcase classname="tests.test_run_command" name="test_run_command_workspace_cwd"/>')
    ok = gate.judge(junit(tmp_path, known + '<testcase classname="tests.test_other" name="test_a"/><testcase classname="tests.test_other" name="test_b"><skipped/></testcase>'), tmp_path)
    assert ok["ok"] and ok["passed"] == 2 and ok["skipped"] == 1
    assert ok["known_env_failures_failing"] == ["tests/test_run_command.py::test_run_command_timeout"]
    assert ok["known_env_failures_passing"] == ["tests/test_run_command.py::test_run_command_workspace_cwd"]
    bad = gate.judge(junit(tmp_path, known + '<testcase classname="tests.test_other.TestThing" name="test_c"><error message="boom"/></testcase>'), tmp_path)
    assert not bad["ok"] and bad["unexpected_failures"] == ["tests/test_other.py::TestThing::test_c"]
    assert not gate.judge(junit(tmp_path, ""), tmp_path)["ok"]


def test_real_repository_frozen_artifacts_verify():
    assert vfa.main(["--root", str(ROOT), "--report", str(ROOT / ".pytest_ci_report_tmp.json")]) == 0
    (ROOT / ".pytest_ci_report_tmp.json").unlink()
