"""Synthetic mechanics tests for the EXEC-D3V2-01 runner.

Fixture data only: no row from `benchmark/results/repo_task_eval.jsonl` is read, no real classification is produced,
and the authoritative `benchmark/analysis/output_v2/` tree is never written. These tests prove the runner's
mechanics — staging refusal, byte-identity definition, promotion, determinism gate, contract-violation stop,
population preflight, membership separation — before the registered execution is authorized.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import benchmark.analysis.run_furthest_bottleneck_classification_v2 as runner

ROOT = Path(__file__).resolve().parents[1]


# ============================================================================= pinned frozen inputs
def test_runner_pins_the_frozen_bundles_and_registered_input():
    assert runner.FREEZE_COMMIT == "f30c5f6fee287774345e701041899668aaa3ec5d"
    assert runner.FREEZE_TAG == "d3-v2-methodology-freeze"
    assert runner.RESULTS_SHA256 == "a242336f4e0b9fa3e467ad39a45b07e97f8994aa2591ffd46a545d4cd5b80978"
    assert runner.EXPECTED_RESULT_ROWS == 620
    assert set(runner.METHODOLOGY_V2) == {
        "benchmark/analysis/furthest_bottleneck_taxonomy_v2.md",
        "benchmark/analysis/furthest_bottleneck_v2.py",
        "benchmark/analysis/furthest_bottleneck_v2_mutations.py",
        "tests/test_furthest_bottleneck_v2.py",
        "tests/test_producer_call_round_contract.py"}
    assert len(runner.FROZEN_V1) == 5 and len(runner.VERIFICATION_TOOLING) == 2


@pytest.mark.parametrize("group", ["METHODOLOGY_V2", "FROZEN_V1", "VERIFICATION_TOOLING"])
def test_pinned_hashes_match_the_files_on_disk(group):
    for rel, expected in getattr(runner, group).items():
        assert runner.sha256_file(rel) == expected, rel


def test_population_definition_matches_the_v1_rule():
    """The same rows, reconstructed — not a new population."""
    assert runner.EXPECTED == {"rows_per_arm": 20, "rows": 120, "solvable": 96,
                               "unsuccessful_solvable": 78, "unsuccessful_per_arm": 13}
    assert [a for a, *_ in runner.ARMS] == ["exp22_drift", "exp18_treatment", "exp20_drift",
                                            "exp20_treatment", "exp21_treatment", "exp22_treatment"]
    assert [r for _, r, *_ in runner.ARMS] == ["primary", "identity", "identity",
                                               "perturbation", "perturbation", "perturbation"]
    v1_runner = (ROOT / "benchmark/analysis/run_furthest_bottleneck_classification.py").read_text(encoding="utf-8")
    for arm, _role, condition, gate in runner.ARMS:      # arm identity is copied from the frozen v1 runner verbatim
        assert f'("{arm}", ' in v1_runner and gate in v1_runner and f'"{condition}"' in v1_runner


# ============================================================================= byte-identity definition
def test_byte_identity_is_defined_before_execution():
    assert runner.SEMANTIC_ARTIFACTS == ("classification_v2.jsonl", "summary_v2.json", "run_identity_v2.json")
    assert runner.EXECUTION_PROVENANCE == "execution_provenance.json"
    assert runner.EXECUTION_PROVENANCE not in runner.SEMANTIC_ARTIFACTS


def test_run_identity_carries_no_execution_specific_field():
    """Semantic identity must be deterministic: no timestamps, pids or paths may leak into it."""
    source = (ROOT / "benchmark/analysis/run_furthest_bottleneck_classification_v2.py").read_text(encoding="utf-8")
    identity_block = source.split("    identity = {", 1)[1].split("\n    return identity", 1)[0]
    for forbidden in ("time.time", "getpid", "staging_path", "datetime", "duration"):
        assert forbidden not in identity_block, forbidden


# ============================================================================= staging refusal
@pytest.mark.parametrize("target", ["benchmark/analysis/output_v2", "benchmark/analysis/output_v2/run_a"])
def test_classify_refuses_to_write_into_the_authoritative_tree(target, monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("preflight must not run: the staging check comes first")

    monkeypatch.setattr(runner, "preflight", fail)
    with pytest.raises(runner.Stop) as stop:
        runner.run_classify(ROOT / target)
    assert "staging" in str(stop.value)


def test_classify_accepts_a_staging_directory_outside_the_authoritative_tree(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "preflight", lambda: calls.append("preflight") or (_ for _ in ()).throw(
        runner.Stop("preflight reached (expected in this test)")))
    with pytest.raises(runner.Stop) as stop:
        runner.run_classify(tmp_path / "run_a")
    assert "preflight reached" in str(stop.value) and calls == ["preflight"]


# ============================================================================= promotion and the determinism gate
def _staged(path: Path, classification: str, summary: dict, identity: dict, provenance: dict) -> Path:
    path.mkdir(parents=True)
    (path / "classification_v2.jsonl").write_text(classification, encoding="utf-8", newline="\n")
    (path / "summary_v2.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n",
                                          encoding="utf-8", newline="\n")
    (path / "run_identity_v2.json").write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n",
                                               encoding="utf-8", newline="\n")
    (path / runner.EXECUTION_PROVENANCE).write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                                                    encoding="utf-8", newline="\n")
    return path


SYNTHETIC_RECORD = {"arm": "exp22_drift", "task": "synthetic_task", "label": "F1",
                    "oracle_replays": [{"error": False}]}
SYNTHETIC_SUMMARY = {"arms": {"exp22_drift": {"oracle_replays": 1, "oracle_replay_errors": 0}}}
SYNTHETIC_IDENTITY = {"execution_id": "EXEC-D3V2-01", "freeze_commit": runner.FREEZE_COMMIT}


def test_promote_requires_byte_identity_and_writes_the_authoritative_set(tmp_path):
    line = runner.dumps_line(SYNTHETIC_RECORD) + "\n"
    a = _staged(tmp_path / "a", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 1, "started_unix": 1.0})
    b = _staged(tmp_path / "b", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 2, "started_unix": 999.0})
    out = tmp_path / "output_v2"
    assert runner.run_promote(a, b, out) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "classification_v2.jsonl", "provenance_v2.json", "run_identity_v2.json", "summary_v2.json"]
    provenance = json.loads((out / "provenance_v2.json").read_text(encoding="utf-8"))
    assert provenance["rerun_identity"] == {"independent_processes": 2, "byte_identical": True,
                                            "artifacts_compared": list(runner.SEMANTIC_ARTIFACTS),
                                            "artifacts_excluded": [runner.EXECUTION_PROVENANCE]}
    assert provenance["classification_sha256"] == runner.sha256_bytes(line.encode("utf-8"))


def test_differing_execution_provenance_does_not_block_promotion(tmp_path):
    """Timestamps and pids differ by nature; only the semantic artifacts gate the promotion."""
    line = runner.dumps_line(SYNTHETIC_RECORD) + "\n"
    a = _staged(tmp_path / "a", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 11, "duration_seconds": 3.2})
    b = _staged(tmp_path / "b", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 22, "duration_seconds": 9.9})
    assert (a / runner.EXECUTION_PROVENANCE).read_bytes() != (b / runner.EXECUTION_PROVENANCE).read_bytes()
    assert runner.run_promote(a, b, tmp_path / "output_v2") == 0


@pytest.mark.parametrize("differing", ["classification_v2.jsonl", "summary_v2.json", "run_identity_v2.json"])
def test_determinism_gate_stops_and_promotes_nothing(tmp_path, differing):
    line = runner.dumps_line(SYNTHETIC_RECORD) + "\n"
    a = _staged(tmp_path / "a", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 1})
    b = _staged(tmp_path / "b", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 2})
    (b / differing).write_text((b / differing).read_text(encoding="utf-8").replace("F1", "F4").replace(
        "EXEC-D3V2-01", "EXEC-OTHER").replace("oracle_replays\": 1", "oracle_replays\": 2"),
        encoding="utf-8", newline="\n")
    out = tmp_path / "output_v2"
    with pytest.raises(runner.Stop) as stop:
        runner.run_promote(a, b, out)
    assert differing in str(stop.value) and "neither result is authoritative" in str(stop.value)
    assert not out.exists()                      # nothing promoted, no tie-break, no selection


def test_promote_refuses_to_overwrite_an_existing_authoritative_output(tmp_path):
    line = runner.dumps_line(SYNTHETIC_RECORD) + "\n"
    a = _staged(tmp_path / "a", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 1})
    b = _staged(tmp_path / "b", line, SYNTHETIC_SUMMARY, SYNTHETIC_IDENTITY, {"pid": 2})
    out = tmp_path / "output_v2"
    out.mkdir()
    with pytest.raises(runner.Stop) as stop:
        runner.run_promote(a, b, out)
    assert "never overwritten" in str(stop.value)


# ============================================================================= contract violations stop the run
def test_a_contract_violating_row_stops_the_run_with_identifying_detail(monkeypatch):
    import benchmark.analysis.furthest_bottleneck_v2 as v2
    from benchmark.repo_tasks import TASKS_BY_NAME

    class FakeRte:
        CONDITIONS = {"qwen_selectorkind": {"overrides": {}}}
        REPOS_DIR = ROOT / "benchmark" / "repos"

        @staticmethod
        def defect_lines(seed, reference):
            return set()

    def raise_violation(*_a, **_k):
        raise v2.RowEnvelopeViolation("calls[1] is str, not a dict")

    monkeypatch.setattr(v2, "extract_facts_v2", raise_violation)
    import benchmark.analysis.furthest_bottleneck as v1
    from core.path_candidates import normalize

    row = {"task": "mathlib_divide_zero", "condition": "qwen_selectorkind", "fingerprint": "fp-1",
           "experiment": {"gate": {"sha256": "abc"}}}
    assert TASKS_BY_NAME.get(row["task"]) is not None
    with pytest.raises(runner.Stop) as stop:
        runner.classify_trajectory(v1, v2, FakeRte, normalize, "exp22_drift", "primary", 42, row)
    detail = json.loads(str(stop.value))["contract_violation"]
    assert detail["arm"] == "exp22_drift" and detail["task"] == "mathlib_divide_zero"
    assert detail["row_line"] == 42 and detail["row_fingerprint"] == "fp-1"
    assert detail["contract"] == "D3_PRODUCER_ENVELOPE_CONTRACT"
    assert detail["violation_type"] == "RowEnvelopeViolation"
    assert "not a dict" in detail["detail"]


# ============================================================================= membership vs transitions
def test_summary_separates_membership_differences_from_label_disagreements():
    def rec(arm, task, label):
        return {"arm": arm, "arm_role": "primary" if arm == "exp22_drift" else "perturbation", "task": task,
                "label": label, "sub_label": None, "d0_harness": "TRUE", "d0_contract": "TRUE",
                "descriptive_facts": {"D3_ATTEMPT_OBSERVED": "TRUE", "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT": "FALSE"},
                "facts": {"D1_D2_defect_known": "TRUE", "D3_evidence": "TRUE", "D4_usable_diagnosis": "FALSE",
                          "D5_localized": "FALSE", "diagnosis_attempted": "TRUE", "proposals": [],
                          "R7": "FALSE", "R8": "FALSE", "R9": "FALSE", "R10": "FALSE",
                          "D11_state_correct": [], "D11_final_state": "FALSE", "D12_regression_evidence": "FALSE",
                          "gold_edit_proposal_exists": False, "non_primitive_attempts": []},
                "history": [], "f5_guard": [], "f6_subtype": None, "oracle_replays": []}

    records = [rec("exp22_drift", "shared_same", "F1"), rec("exp22_drift", "shared_diff", "F4"),
               rec("exp22_drift", "only_primary", "F0"),
               rec("exp22_treatment", "shared_same", "F1"), rec("exp22_treatment", "shared_diff", "F6"),
               rec("exp22_treatment", "only_arm", "F0")]
    summary = runner.summarize(records)
    arm = summary["agreement_with_primary"]["exp22_treatment"]
    assert arm["comparable_tasks"] == 2 and arm["same_label"] == 1
    assert [d["task"] for d in arm["disagreements"]] == ["shared_diff"]
    assert arm["membership_difference"] == {"only_in_primary": ["only_primary"], "only_in_this_arm": ["only_arm"]}


def test_transitions_compare_only_matching_fingerprints(tmp_path):
    def v1_rec(task, label, d3, fp):
        return {"arm": "exp22_drift", "task": task, "row_fingerprint": fp, "label": label, "sub_label": None,
                "facts": {"D3_evidence": d3}}

    def v2_rec(task, label, d3, fp):
        return dict(v1_rec(task, label, d3, fp), methodology="D3-v2")

    v1_dir, v2_dir = tmp_path / "v1", tmp_path / "v2"
    v1_dir.mkdir(), v2_dir.mkdir()
    (v1_dir / "classification.jsonl").write_text(
        runner.dumps_line(v1_rec("t_same", "F0", "FALSE", "fp1")) + "\n"
        + runner.dumps_line(v1_rec("t_changed", "F0", "FALSE", "fp2")) + "\n"
        + runner.dumps_line(v1_rec("t_only_v1", "F4", "TRUE", "fp3")) + "\n", encoding="utf-8", newline="\n")
    (v2_dir / "classification_v2.jsonl").write_text(
        runner.dumps_line(v2_rec("t_same", "F0", "FALSE", "fp1")) + "\n"
        + runner.dumps_line(v2_rec("t_changed", "F1", "TRUE", "fp2")) + "\n"
        + runner.dumps_line(v2_rec("t_only_v1", "F4", "TRUE", "fp-different")) + "\n",
        encoding="utf-8", newline="\n")
    out = tmp_path / "transitions.json"
    assert runner.run_transitions(v1_dir, v2_dir, out) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["comparable_rows"] == 2                       # the mismatched fingerprint is excluded
    assert report["label_transitions"] == {"F0->F0": 1, "F0->F1": 1}
    assert report["d3_evidence_transitions"] == {"FALSE->FALSE": 1, "FALSE->TRUE": 1}
    assert [c["task"] for c in report["changed_rows"]] == ["t_changed"]
    assert report["non_comparable"]["only_in_v1"] == [["exp22_drift", "t_only_v1", "fp3"]]
    assert report["non_comparable"]["only_in_v2"] == [["exp22_drift", "t_only_v1", "fp-different"]]


# ============================================================================= the runner never touches v1 output
def test_runner_never_writes_to_the_v1_output_tree():
    source = (ROOT / "benchmark/analysis/run_furthest_bottleneck_classification_v2.py").read_text(encoding="utf-8")
    assert 'V1_OUTPUT = "benchmark/analysis/output"' in source
    for write_call in ("_write(", "shutil.copyfile(", "os.replace("):
        for line in source.splitlines():
            if write_call in line and "V1_OUTPUT" in line:
                pytest.fail(f"v1 output tree used as a write target: {line.strip()}")


def test_cli_exposes_only_the_three_intended_modes():
    proc = subprocess.run([sys.executable, str(ROOT / "benchmark/analysis/run_furthest_bottleneck_classification_v2.py"),
                           "--help"], capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0
    assert "classify" in proc.stdout and "promote" in proc.stdout and "transitions" in proc.stdout
