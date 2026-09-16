"""MV-02C local tests: injected/fake machinery ONLY.

No test in this file calls the frozen resource_monitor_v1.run_monitored. The first complete execution of
C1-C10 against frozen v1 happens on CI through the mv02c_enforcement CLI (spec v2.1, approved plan).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.monitor_validity_v2 import FAIL, INVALID, PASS, SPEC_PATH, VALID  # noqa: E402
from scripts.monitor_validity_v2 import mv02c_enforcement as mc  # noqa: E402

SPEC = SPEC_PATH.read_text(encoding="utf-8")


class FakeMonitor:
    """Imitates the frozen probe call order with a sampler thread whose target is named `loop`.

    fail_open=True mimics a gate evaluated over prior samples after sampler death; fail_open=False mimics a
    monitor whose gate fails when sampling stopped early. skip_second_processes breaks the call order.
    """

    def __init__(self, samples: int, *, fail_open: bool = True, skip_second_processes: bool = False,
                 raise_in_caller: bool = False) -> None:
        self.samples = samples
        self.fail_open = fail_open
        self.skip_second_processes = skip_second_processes
        self.raise_in_caller = raise_in_caller

    def run_monitored(self, command, *, probe, discover_ollama, max_seconds):
        assert discover_ollama is False and max_seconds == mc.C_MAX_SECONDS
        probe.processes()
        probe.available_memory_bytes()
        readings: list = []
        died = []

        def loop():
            for _ in range(self.samples):
                probe.processes()
                if not self.skip_second_processes:
                    probe.processes()
                readings.append(probe.available_memory_bytes())
            died.append(False)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        thread.join(timeout=5)
        stopped_early = not died
        if self.raise_in_caller:
            raise TypeError("caller-side failure")
        ints = [r for r in readings if isinstance(r, int)]
        passed = bool(ints) and min(ints) >= mc.RESERVE_BYTES
        if stopped_early and not self.fail_open:
            passed = False
        return None, {"events": [], "watchdog_abort": False, "returncode": 0,
                      "gate": {"passed": passed, "conditions": {mc.MIN_CONDITION: passed}}}


def _case(case_id):
    return next(c for c in mc.CASES if c.case_id == case_id)


def test_cases_are_pinned_exactly_as_the_frozen_specification():
    ids = [c.case_id for c in mc.CASES]
    assert ids == ["C1", "C2", "C3", "C4", "C5", "C6", "C7a", "C7b", "C8", "C9", "C10"]
    assert _case("C2").below == (1,)
    assert _case("C3").below == tuple(range(1, 8))
    assert _case("C4").below == tuple(range(2, 10))
    assert _case("C5").below == tuple(range(1, 8)) + tuple(range(9, 16))
    assert 8 not in _case("C5").below
    assert _case("C9").fault_call == 5 and _case("C10").fault_call == 1
    assert _case("C7a").none_at == 0 and _case("C7b").none_at == 3
    assert _case("C6").equal_reserve
    assert [c.min_samples for c in mc.CASES] == [4, 4, 9, 10, 16, 10, 1, 4, 2, 2, 0]
    assert [c.child_sleep for c in mc.CASES] == [3.0, 3.0, 4.0, 10.0, 6.0, 4.0, 3.0, 3.0, 2.0, 4.0, 3.0]
    assert _case("C8").child_exit == 3
    assert _case("C2").expected["classification"] == mc.SAFE_GATE_FAIL
    assert _case("C2").expected["gate_passed"] is False and _case("C2").expected["abort"] is False
    assert _case("C4").expected["abort_index"] == 9
    for case_id in ("C7a", "C7b", "C9", "C10"):
        assert _case(case_id).expected == mc.NOT_SILENT_PASS
    assert mc.C_MAX_SECONDS == 30
    assert "sampler-loop processes() call 5" in SPEC and "gate passed | 4 |" not in SPEC.split("| C2 |")[1].split("\n")[0]


def test_predictions_are_verbatim_from_the_frozen_specification():
    for case_id, text in mc.PREDICTIONS.items():
        assert text in SPEC, case_id


def test_readings_follow_the_indexing_domains():
    c5 = _case("C5")
    assert c5.reading(0) == mc.ABOVE and c5.reading(8) == mc.ABOVE and c5.reading(16) == mc.ABOVE
    assert all(c5.reading(i) == mc.BELOW for i in list(range(1, 8)) + list(range(9, 16)))
    assert _case("C6").reading(0) == mc.RESERVE_BYTES
    assert _case("C7b").reading(3) is None and _case("C7b").reading(2) == mc.ABOVE


def test_scripted_probe_records_frozen_call_order_and_injects_fault_at_call_5():
    probe = mc.ScriptedProbe(_case("C9"))
    probe.processes()
    assert probe.available_memory_bytes() == mc.ABOVE  # preflight read, outside the sample sequence
    for _ in range(2):
        probe.processes()
        probe.processes()
        assert probe.available_memory_bytes() == mc.ABOVE
    with pytest.raises(mc.rm.MonitorError):
        probe.processes()
    assert probe.samples_taken == 2 and probe.fault_raised and probe.call_order_ok()


def test_call_order_rejects_truncated_group_without_fault():
    probe = mc.ScriptedProbe(_case("C1"))
    probe.processes()
    probe.available_memory_bytes()
    probe.processes()
    probe.available_memory_bytes()
    assert not probe.call_order_ok()


def test_fail_open_sampler_death_is_classified_silent_gate_pass_and_fails_c(tmp_path):
    record, provenance = mc.run_case(_case("C9"), tmp_path, monitor=FakeMonitor(samples=6, fail_open=True))
    assert record["sampler"]["outcome"] == "DIED_WITH_EXCEPTION"
    hook = record["sampler"]["excepthook"][0]
    assert hook["exc_type"] == "MonitorError" and hook["sampler_thread"] is True and "thread_name" not in hook
    assert provenance["excepthook_all"][0]["thread_name"].endswith("(loop)")
    assert "call 5" in hook["message"]
    assert record["exception"] is None and record["watchdog"]["abort"] is False
    assert record["gate"]["passed"] is True
    assert record["classification"] == mc.SILENT_SAMPLER_DEATH_GATE_PASS
    assert record["match"] is False and record["run_status"] == VALID
    assert record["checks"]["samples_taken"] == 2
    assert provenance["samples_taken"] == 2


def test_fail_closed_sampler_death_is_acceptable(tmp_path):
    record, _ = mc.run_case(_case("C9"), tmp_path, monitor=FakeMonitor(samples=6, fail_open=False))
    assert record["classification"] == mc.SILENT_SAMPLER_DEATH_GATE_FAIL
    assert record["match"] is True and record["run_status"] == VALID


def test_call_order_mismatch_is_invalid_not_fail(tmp_path):
    record, _ = mc.run_case(_case("C1"), tmp_path, monitor=FakeMonitor(samples=6, skip_second_processes=True))
    assert record["run_status"] == INVALID
    assert any("call-order" in reason for reason in record["invalid_reasons"])


def test_minimum_samples_shortfall_is_invalid_not_fail(tmp_path):
    record, _ = mc.run_case(_case("C5"), tmp_path, monitor=FakeMonitor(samples=3))
    assert record["run_status"] == INVALID
    assert any("minimum samples" in reason for reason in record["invalid_reasons"])


def test_exception_raised_to_the_caller_after_sampling_is_observed(tmp_path):
    record, _ = mc.run_case(_case("C7b"), tmp_path, monitor=FakeMonitor(samples=6, raise_in_caller=True))
    assert record["classification"] == mc.EXCEPTION_PROPAGATED
    assert record["exception"]["type"] == "TypeError"
    assert record["match"] is True


def _record(**overrides):
    base = {"exception": None, "gate": {"passed": False, "conditions": {}},
            "sampler": {"outcome": "NORMAL_STOP"}, "watchdog": {"abort": False, "sample_index": None},
            "events": []}
    base.update(overrides)
    return base


def test_classifier_covers_all_six_classes():
    assert mc.classify(_record(exception={"type": "TypeError", "message": ""})) == mc.EXCEPTION_PROPAGATED
    assert mc.classify(_record(gate={"passed": True, "conditions": {}})) == mc.NOMINAL
    assert mc.classify(_record(watchdog={"abort": True, "sample_index": 9})) == mc.NOMINAL
    assert mc.classify(_record()) == mc.SAFE_GATE_FAIL
    died = {"outcome": "DIED_WITH_EXCEPTION"}
    assert mc.classify(_record(sampler=died)) == mc.SILENT_SAMPLER_DEATH_GATE_FAIL
    assert mc.classify(_record(sampler=died, events=[{"event": "sampler_failure"}])) == mc.SAMPLER_FAILURE_SURFACED
    assert mc.classify(_record(sampler=died, gate={"passed": True, "conditions": {}})) == \
        mc.SILENT_SAMPLER_DEATH_GATE_PASS


def _valid_records(match=True, classification=mc.NOMINAL):
    return [{"case_id": c.case_id, "match": match, "classification": classification, "run_status": VALID,
             "invalid_reasons": []} for c in mc.CASES]


def test_evaluate_pass_fail_invalid():
    assert mc.evaluate(_valid_records())["c_verdict"] == PASS
    records = _valid_records()
    records[10] = {**records[10], "match": False, "classification": mc.SILENT_SAMPLER_DEATH_GATE_PASS}
    result = mc.evaluate(records)
    assert result["c_verdict"] == FAIL and result["silent_sampler_death_gate_pass_cases"] == ["C10"]
    records = _valid_records()
    records[3] = {**records[3], "run_status": INVALID, "invalid_reasons": ["minimum samples not reached"]}
    result = mc.evaluate(records)
    assert result["run_status"] == INVALID and result["c_verdict"] is None
    assert mc.evaluate(_valid_records()[:5])["run_status"] == INVALID


def test_harness_errors_become_invalid_records(tmp_path):
    def broken(case, scratch):
        raise OSError("cannot write child")
    records, _ = mc.run_suite(tmp_path, case_runner=broken)
    assert all(r["run_status"] == INVALID for r in records)
    assert mc.evaluate(records)["c_verdict"] is None


def test_evidence_serialization_is_deterministic():
    records = _valid_records()
    first = mc.serialize(mc.build_evidence(records, commit_sha="abc"))
    second = mc.serialize(mc.build_evidence(records, commit_sha="abc"))
    assert first == second and first.endswith(b"\n") and b"\r" not in first
    document = mc.build_evidence(records, commit_sha="abc")
    assert document["spec_sha256"] == "e14b533363bee0bc946e6dfddbbfc516b1b195be3dbbbb8d75644c17eb0ae585"
    assert document["resource_monitor_v1_sha256"] == \
        "a1940a1b2c03320b9ec9fd4abb6aba3b51f62011aaebec4dd66016a3cc997003"
    assert document["preregistered_predictions"] == mc.PREDICTIONS


def test_cli_refuses_to_run_the_real_suite_outside_github_actions(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert mc.main(["--out-dir", str(tmp_path / "out")]) == mc.EXIT_REFUSED
    assert not (tmp_path / "out").exists()


def test_orchestration_failure_has_a_distinct_exit_code(monkeypatch):
    def explode(argv):
        raise RuntimeError("orchestration")
    monkeypatch.setattr(mc, "_main", explode)
    assert mc.main([]) == mc.EXIT_ORCHESTRATION
    assert len({mc.EXIT_PASS, mc.EXIT_FAIL, mc.EXIT_INVALID, mc.EXIT_ORCHESTRATION, mc.EXIT_REFUSED}) == 5


def _write_evidence(directory, run_status, verdict, schema=mc.EVIDENCE_SCHEMA):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "mv02c_evidence.json").write_bytes(
        mc.serialize({"schema": schema, "run_status": run_status, "c_verdict": verdict}))


def test_ci_status_distinguishes_pass_fail_invalid_and_orchestration_failure(tmp_path):
    _write_evidence(tmp_path / "pass", VALID, PASS)
    assert mc.ci_status(tmp_path / "pass", mc.EXIT_PASS)["status"] == "PASS"
    _write_evidence(tmp_path / "fail", VALID, FAIL)
    fail = mc.ci_status(tmp_path / "fail", mc.EXIT_FAIL)
    assert fail["status"] == "FAIL" and len(fail["evidence_sha256"]) == 64
    _write_evidence(tmp_path / "invalid", INVALID, None)
    assert mc.ci_status(tmp_path / "invalid", mc.EXIT_INVALID)["status"] == "INVALID"
    assert mc.ci_status(tmp_path / "missing", mc.EXIT_FAIL)["status"] == "ORCHESTRATION_FAILURE"
    assert mc.ci_status(tmp_path / "fail", mc.EXIT_PASS)["status"] == "ORCHESTRATION_FAILURE"
    assert mc.ci_status(tmp_path / "fail", mc.EXIT_ORCHESTRATION)["status"] == "ORCHESTRATION_FAILURE"
    _write_evidence(tmp_path / "schema", VALID, PASS, schema="other")
    assert mc.ci_status(tmp_path / "schema", mc.EXIT_PASS)["status"] == "ORCHESTRATION_FAILURE"
    (tmp_path / "garbled").mkdir()
    (tmp_path / "garbled" / "mv02c_evidence.json").write_text("{", encoding="utf-8")
    assert mc.ci_status(tmp_path / "garbled", mc.EXIT_PASS)["status"] == "ORCHESTRATION_FAILURE"


def test_classify_mode_never_executes_cases(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    _write_evidence(tmp_path, VALID, FAIL)
    monkeypatch.setattr(mc, "run_suite", lambda *a, **k: (_ for _ in ()).throw(AssertionError("executed")))
    assert mc.main(["--out-dir", str(tmp_path), "--classify-exit-code", "1"]) == 0
    assert b'"status": "FAIL"' in (tmp_path / "mv02c_status.json").read_bytes()
