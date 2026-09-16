"""MV-02C enforcement validity (spec v2.1 §6).

Runs the pinned cases C1-C10 against the frozen resource_monitor_v1.run_monitored through its supported
`probe=` parameter. ScriptedProbe supplies the resource-value inputs so no real memory pressure is involved;
the child processes, the sampler thread, termination and the gate are the real frozen code paths.

Indexing domains (spec v2.1 §6, never interchanged):
  preflight read         available_memory_bytes() call 0; OUTSIDE the sample-index sequence
  sample index           0-based over samples taken by the sampler loop
  sampler-loop call no.  1-based over processes() calls made by the sampler loop (preflight excluded);
                         sample index i uses sampler-loop processes() calls 2i+1 and 2i+2

Sampler death is observed DIRECTLY through threading.excepthook (Python 3.8+; args.exc_type, exc_value,
exc_traceback, thread). The hook copies the type name, message and thread name at hook time and retains
neither the exception nor the thread object. The frozen sampler thread is created with target `loop` and no
explicit name, so Python names it "Thread-N (loop)". Thread enumeration after return is corroboration only.

The complete real suite runs ONLY through this module's CLI, which refuses to run outside GitHub Actions.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import resource_monitor_v1 as rm  # noqa: E402
from scripts.monitor_validity_v2 import (  # noqa: E402
    FAIL, INVALID, MONITOR_V1_PATH, PASS, SPEC_PATH, VALID, children, sha256_file,
)

MIB = rm.MIB
RESERVE_BYTES = rm.RESERVE_MIB * MIB
ABOVE = RESERVE_BYTES + 1024 * MIB
BELOW = RESERVE_BYTES // 2
C_MAX_SECONDS = 30
SAMPLER_THREAD_SUFFIX = "(loop)"

EVIDENCE_SCHEMA = "mv02c_evidence_v1"
PROVENANCE_SCHEMA = "mv02c_evidence_provenance_v1"

# Safety classifications (spec v2.1 §6).
NOMINAL = "NOMINAL"
SAFE_GATE_FAIL = "SAFE_GATE_FAIL"
EXCEPTION_PROPAGATED = "EXCEPTION_PROPAGATED"
SAMPLER_FAILURE_SURFACED = "SAMPLER_FAILURE_SURFACED"
SILENT_SAMPLER_DEATH_GATE_FAIL = "SILENT_SAMPLER_DEATH_GATE_FAIL"
SILENT_SAMPLER_DEATH_GATE_PASS = "SILENT_SAMPLER_DEATH_GATE_PASS"
CLASSIFICATIONS = (NOMINAL, SAFE_GATE_FAIL, EXCEPTION_PROPAGATED, SAMPLER_FAILURE_SURFACED,
                   SILENT_SAMPLER_DEATH_GATE_FAIL, SILENT_SAMPLER_DEATH_GATE_PASS)

MIN_CONDITION = "sampled_available_min_at_or_above_reserve"
DEATH_CONDITION = "zero_oom_or_process_death"

# Preregistered static predictions, verbatim from the frozen specification (prediction, not evidence).
PREDICTIONS = {
    "C9": "C9 — POSSIBLE FAIL-OPEN SAMPLER-FAILURE PATH: the sampler loop in resource_monitor_v1.run_monitored "
          "has no try; the exception terminates the daemon thread without an event; the child continues without "
          "watchdog; summarize sees only the 2 valid samples; evaluate_gate passes if they are >= reserve and the "
          "child exits 0. Predicted classification SILENT_SAMPLER_DEATH_GATE_PASS → C FAIL.",
    "C10": "C10: zero samples → sampled_available_min_bytes UNKNOWN → gate fails. Predicted "
           "SILENT_SAMPLER_DEATH_GATE_FAIL (acceptable, DIAGNOSTIC).",
    "C7a": "C7a: the None sample is appended, then `None < reserve` raises TypeError in the thread; summarize "
           "minimum is None, not int → gate fails. Predicted SILENT_SAMPLER_DEATH_GATE_FAIL (acceptable, DIAGNOSTIC).",
    "C7b": "C7b: min over ints and None raises TypeError in summarize on the calling thread. Predicted "
           "EXCEPTION_PROPAGATED (acceptable).",
}


# ============================================================================= cases

@dataclass(frozen=True)
class Case:
    case_id: str
    script: str
    child_sleep: float
    child_exit: int
    min_samples: int
    below: tuple[int, ...] = ()
    none_at: int | None = None
    equal_reserve: bool = False
    fault_call: int | None = None
    expected: dict[str, Any] = field(default_factory=dict)

    def reading(self, sample_index: int) -> int | None:
        if self.none_at is not None and sample_index == self.none_at:
            return None
        if self.equal_reserve:
            return RESERVE_BYTES
        return BELOW if sample_index in self.below else ABOVE


def _exact(classification: str, *, abort: bool, gate_passed: bool, abort_index: int | None = None,
           event_names: Sequence[str] | None = None, failed_condition: str | None = None,
           child_status: str | None = None) -> dict[str, Any]:
    return {"kind": "exact", "classification": classification, "abort": abort, "abort_index": abort_index,
            "gate_passed": gate_passed, "event_names": list(event_names) if event_names is not None else None,
            "failed_condition": failed_condition, "child_status": child_status}


NOT_SILENT_PASS = {"kind": "not_classification", "classification": SILENT_SAMPLER_DEATH_GATE_PASS}

CASES: tuple[Case, ...] = (
    Case("C1", "all readings >= reserve + 1 GiB", 3.0, 0, 4,
         expected=_exact(NOMINAL, abort=False, gate_passed=True, event_names=[])),
    Case("C2", "below reserve at sample index 1; all other readings above reserve", 3.0, 0, 4,
         below=(1,), expected=_exact(SAFE_GATE_FAIL, abort=False, gate_passed=False, failed_condition=MIN_CONDITION)),
    Case("C3", "below reserve at sample indices 1..7 inclusive; all other readings above reserve", 4.0, 0, 9,
         below=tuple(range(1, 8)),
         expected=_exact(SAFE_GATE_FAIL, abort=False, gate_passed=False, failed_condition=MIN_CONDITION)),
    Case("C4", "exactly 8 consecutive below starting at sample index 2", 10.0, 0, 10,
         below=tuple(range(2, 10)),
         expected=_exact(NOMINAL, abort=True, abort_index=9, gate_passed=False, event_names=["watchdog_abort"],
                         child_status="terminated")),
    Case("C5", "below reserve at sample indices 1..7 inclusive; above reserve at sample index 8; below reserve at "
               "sample indices 9..15 inclusive; all other readings above reserve", 6.0, 0, 16,
         below=tuple(range(1, 8)) + tuple(range(9, 16)),
         expected=_exact(SAFE_GATE_FAIL, abort=False, gate_passed=False, failed_condition=MIN_CONDITION)),
    Case("C6", "at least 10 readings exactly equal to reserve", 4.0, 0, 10, equal_reserve=True,
         expected=_exact(NOMINAL, abort=False, gate_passed=True)),
    Case("C7a", "first sampler reading None", 3.0, 0, 1, none_at=0, expected=NOT_SILENT_PASS),
    Case("C7b", "3 valid readings then None", 3.0, 0, 4, none_at=3, expected=NOT_SILENT_PASS),
    Case("C8", "all above; child sys.exit(3) after 2 s", 2.0, 3, 2,
         expected=_exact(SAFE_GATE_FAIL, abort=False, gate_passed=False, event_names=["nonzero_exit"],
                         failed_condition=DEATH_CONDITION)),
    Case("C9", "probe raises MonitorError on sampler-loop processes() call 5; exactly 2 valid samples before the "
               "fault; child continues sleeping 4 s, exit 0", 4.0, 0, 2, fault_call=5, expected=NOT_SILENT_PASS),
    Case("C10", "probe raises on the first sampler-loop call", 3.0, 0, 0, fault_call=1, expected=NOT_SILENT_PASS),
)


# ============================================================================= scripted probe

class ScriptedProbe:
    """SystemProbe supplying pinned readings and recording the frozen call order."""

    def __init__(self, case: Case) -> None:
        self.case = case
        self._lock = threading.Lock()
        self.tokens: list[str] = []
        self.processes_calls = 0
        self.available_calls = 0
        self.fault_raised = False
        self.none_delivered = False

    def total_memory_bytes(self) -> int:
        return 8 * 1024 * MIB

    def committed_bytes(self) -> int | None:
        return None

    def listener_pids(self, port: int) -> list[int]:
        return []

    def processes(self) -> list[rm.ProcessInfo]:
        with self._lock:
            self.processes_calls += 1
            if self.processes_calls == 1:
                self.tokens.append("preflight_processes")
            else:
                call_number = self.processes_calls - 1
                self.tokens.append("P")
                if self.case.fault_call == call_number:
                    self.fault_raised = True
                    raise rm.MonitorError(f"scripted sampler fault at sampler-loop processes() call {call_number}")
        return [rm.ProcessInfo(pid=os.getpid(), name="mv02c-harness", ppid=0, rss_bytes=64 * MIB, page_faults=None)]

    def available_memory_bytes(self) -> int | None:
        with self._lock:
            self.available_calls += 1
            if self.available_calls == 1:
                self.tokens.append("preflight_available")
                return ABOVE
            self.tokens.append("A")
            value = self.case.reading(self.available_calls - 2)
            if value is None:
                self.none_delivered = True
            return value

    @property
    def sampler_tokens(self) -> list[str]:
        return self.tokens[2:]

    @property
    def samples_taken(self) -> int:
        return self.sampler_tokens.count("A")

    def call_order_ok(self) -> bool:
        if self.tokens[:2] != ["preflight_processes", "preflight_available"]:
            return False
        rest = self.sampler_tokens
        full, remainder = divmod(len(rest), 3)
        if any(rest[3 * i:3 * i + 3] != ["P", "P", "A"] for i in range(full)):
            return False
        if remainder == 0:
            return True
        # A truncated group is legitimate only when it ends exactly at the injected fault.
        tail = rest[3 * full:]
        return self.fault_raised and all(token == "P" for token in tail) \
            and (2 * full + len(tail)) == self.case.fault_call


class ExceptHookRecorder:
    """Temporarily replaces threading.excepthook; copies facts, never retains exception or thread objects."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self._previous: Callable[..., Any] | None = None

    def _hook(self, args: Any) -> None:
        thread = args.thread
        name = thread.name if thread is not None else None
        self.records.append({
            "exc_type": args.exc_type.__name__ if args.exc_type is not None else None,
            "message": str(args.exc_value) if args.exc_value is not None else None,
            "thread_name": name,
            "thread_ident_captured": bool(thread is not None and thread.ident is not None),
            "sampler_thread": bool(name and name.endswith(SAMPLER_THREAD_SUFFIX)),
        })

    def __enter__(self) -> "ExceptHookRecorder":
        self._previous = threading.excepthook
        threading.excepthook = self._hook
        return self

    def __exit__(self, *exc: Any) -> None:
        threading.excepthook = self._previous  # type: ignore[assignment]


# ============================================================================= classification

def classify(record: Mapping[str, Any]) -> str:
    """Safety classification from recorded observations only (spec v2.1 §6 table).

    Any sampler death together with gate.passed == True is classified SILENT_SAMPLER_DEATH_GATE_PASS: the
    specification's safety semantics are that sampler failure must never yield a passing gate.
    """
    if record["exception"] is not None:
        return EXCEPTION_PROPAGATED
    passed = bool(record["gate"]["passed"])
    if record["sampler"]["outcome"] == "DIED_WITH_EXCEPTION":
        if passed:
            return SILENT_SAMPLER_DEATH_GATE_PASS
        surfaced = any("sampler" in str(event.get("event", "")) for event in record["events"] or [])
        return SAMPLER_FAILURE_SURFACED if surfaced else SILENT_SAMPLER_DEATH_GATE_FAIL
    if record["watchdog"]["abort"]:
        return NOMINAL
    return NOMINAL if passed else SAFE_GATE_FAIL


def matches_expectation(case: Case, record: Mapping[str, Any]) -> bool:
    expected = case.expected
    observed = record["classification"]
    if expected["kind"] == "not_classification":
        return observed != expected["classification"]
    if observed != expected["classification"] or record["exception"] is not None:
        return False
    if record["watchdog"]["abort"] != expected["abort"]:
        return False
    if expected["abort_index"] is not None and record["watchdog"]["sample_index"] != expected["abort_index"]:
        return False
    if bool(record["gate"]["passed"]) != expected["gate_passed"]:
        return False
    if expected["event_names"] is not None and [e.get("event") for e in record["events"]] != expected["event_names"]:
        return False
    if expected["failed_condition"] is not None \
            and record["gate"]["conditions"].get(expected["failed_condition"]) is not False:
        return False
    if expected["child_status"] is not None and record["child"]["status"] != expected["child_status"]:
        return False
    return True



# ============================================================================= execution

def run_case(case: Case, scratch: Path, *, monitor: Any = rm) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one case through `monitor.run_monitored`. Returns (semantic record, provenance)."""
    child, child_sha = children.write_child(Path(scratch), children.C_SLEEP)
    command = [sys.executable, str(child), "--sleep", str(case.child_sleep), "--exit-code", str(case.child_exit)]
    probe = ScriptedProbe(case)
    before = {thread.ident for thread in threading.enumerate()}
    artifact: dict[str, Any] | None = None
    state: Any = None
    exception: dict[str, str] | None = None
    with ExceptHookRecorder() as hooks:
        try:
            state, artifact = monitor.run_monitored(command, probe=probe, discover_ollama=False,
                                                    max_seconds=C_MAX_SECONDS)
        except Exception as exc:  # observed outcome of the instrument, recorded, never swallowed silently
            exception = {"type": type(exc).__name__, "message": str(exc)}
    alive_new_sampler = [t.name for t in threading.enumerate()
                         if t.ident not in before and t.name.endswith(SAMPLER_THREAD_SUFFIX) and t.is_alive()]

    invalid_reasons: list[str] = []
    if exception is not None and not probe.sampler_tokens:
        invalid_reasons.append(f"run_monitored raised before any sampling (harness or spawn error): "
                               f"{exception['type']}")

    sampler_hooks = [h for h in hooks.records if h["sampler_thread"]]
    if sampler_hooks:
        sampler_outcome = "DIED_WITH_EXCEPTION"
    elif artifact is not None and artifact.get("watchdog_abort"):
        sampler_outcome = "WATCHDOG_RETURN"
    elif alive_new_sampler:
        sampler_outcome = "STILL_ALIVE"
    else:
        sampler_outcome = "NORMAL_STOP"

    events = list(artifact["events"]) if artifact is not None else None
    abort_event = next((e for e in events or [] if e.get("event") == "watchdog_abort"), None)
    if artifact is None:
        child_status = "unknown_run_monitored_raised"
    elif any(e.get("event") == "timeout" for e in events or []):
        child_status = "timeout"
    elif artifact.get("watchdog_abort"):
        child_status = "terminated"
    else:
        child_status = "completed"

    deterministic_sampling = bool(case.fault_call is not None or case.none_at is not None
                                  or (artifact is not None and artifact.get("watchdog_abort")))
    record: dict[str, Any] = {
        "case_id": case.case_id,
        "script": case.script,
        "expected": case.expected,
        "child": {"status": child_status,
                  "returncode": artifact.get("returncode") if artifact is not None else None},
        "sampler": {"outcome": sampler_outcome,
                    # thread names ("Thread-N (loop)") vary between runs: provenance only, never semantic
                    "excepthook": [{k: h[k] for k in ("exc_type", "message", "sampler_thread",
                                                      "thread_ident_captured")} for h in sampler_hooks],
                    "still_alive_after_return": bool(alive_new_sampler)},
        "watchdog": {"abort": bool(artifact.get("watchdog_abort")) if artifact is not None else False,
                     "sample_index": abort_event.get("sample_index") if abort_event else None},
        "events": events,
        "exception": exception,
        "gate": {"passed": artifact["gate"]["passed"], "conditions": artifact["gate"]["conditions"]}
        if artifact is not None else {"passed": False, "conditions": {}},
        "checks": {
            "call_order_ok": probe.call_order_ok(),
            "min_samples": case.min_samples,
            "min_samples_met": probe.samples_taken >= case.min_samples,
            "fault_injected": probe.fault_raised if case.fault_call is not None else None,
            "none_delivered": probe.none_delivered if case.none_at is not None else None,
            "samples_taken": probe.samples_taken if deterministic_sampling else None,
        },
    }
    if not record["checks"]["call_order_ok"]:
        invalid_reasons.append("frozen call-order self-check failed")
    if not record["checks"]["min_samples_met"]:
        invalid_reasons.append(f"minimum samples not reached ({probe.samples_taken} < {case.min_samples})")
    if case.fault_call is not None and not probe.fault_raised:
        invalid_reasons.append("scripted fault was never reached")
    if case.none_at is not None and not probe.none_delivered:
        invalid_reasons.append("scripted None reading was never delivered")
    record["classification"] = classify(record)
    record["match"] = matches_expectation(case, record)
    record["run_status"] = INVALID if invalid_reasons else VALID
    record["invalid_reasons"] = invalid_reasons
    provenance = {
        "case_id": case.case_id,
        "child_sha256": child_sha,
        "samples_taken": probe.samples_taken,
        "state_samples": len(state.samples) if state is not None else None,
        "threads_alive_after_return": alive_new_sampler,
        "excepthook_all": hooks.records,
    }
    return record, provenance


def harness_error_record(case: Case, exc: BaseException) -> tuple[dict[str, Any], dict[str, Any]]:
    record = {"case_id": case.case_id, "script": case.script, "expected": case.expected, "classification": None,
              "match": False, "run_status": INVALID,
              "invalid_reasons": [f"harness error outside run_monitored: {type(exc).__name__}: {exc}"]}
    return record, {"case_id": case.case_id, "traceback": traceback.format_exc()}


def evaluate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Two-state verdict plus INVALID (spec v2.1 §6). INVALID is a run status, never a verdict."""
    invalid = [f"{r['case_id']}: {reason}" for r in records for reason in r["invalid_reasons"]]
    if invalid or len(records) != len(CASES):
        if len(records) != len(CASES):
            invalid.append(f"{len(records)} case records; {len(CASES)} required")
        return {"run_status": INVALID, "c_verdict": None, "invalid_reasons": invalid, "mismatched_cases": []}
    mismatched = [r["case_id"] for r in records if not r["match"]]
    silent_pass = [r["case_id"] for r in records if r["classification"] == SILENT_SAMPLER_DEATH_GATE_PASS]
    verdict = FAIL if mismatched or silent_pass else PASS
    return {"run_status": VALID, "c_verdict": verdict, "invalid_reasons": [], "mismatched_cases": mismatched,
            "silent_sampler_death_gate_pass_cases": silent_pass}


def run_suite(scratch: Path, *, monitor: Any = rm,
              case_runner: Callable[[Case, Path], tuple[dict[str, Any], dict[str, Any]]] | None = None
              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for case in CASES:
        try:
            if case_runner is not None:
                record, prov = case_runner(case, Path(scratch))
            else:
                record, prov = run_case(case, Path(scratch), monitor=monitor)
        except Exception as exc:
            record, prov = harness_error_record(case, exc)
        records.append(record)
        provenance.append(prov)
    return records, provenance


def build_evidence(records: Sequence[Mapping[str, Any]], *, commit_sha: str | None) -> dict[str, Any]:
    result = evaluate(records)
    c9 = next((r for r in records if r["case_id"] == "C9"), None)
    return {
        "schema": EVIDENCE_SCHEMA,
        "spec_path": "benchmark/analysis/monitor_validity_v2_1.md",
        "spec_sha256": sha256_file(SPEC_PATH),
        "resource_monitor_v1_sha256": sha256_file(MONITOR_V1_PATH),
        "commit_sha": commit_sha,
        "python_version": platform.python_version(),
        "sys_platform": sys.platform,
        "reserve_bytes": RESERVE_BYTES,
        "scripted_values": {"above_bytes": ABOVE, "below_bytes": BELOW, "max_seconds": C_MAX_SECONDS},
        "preregistered_predictions": PREDICTIONS,
        "cases": list(records),
        "c9_observed_classification": c9.get("classification") if c9 else None,
        **result,
    }


def serialize(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode("utf-8")


EXIT_PASS, EXIT_FAIL, EXIT_INVALID, EXIT_ORCHESTRATION, EXIT_REFUSED = 0, 1, 3, 4, 5


C_STATUS_PASS, C_STATUS_FAIL = "PASS", "FAIL"
C_STATUS_INVALID, C_STATUS_ORCHESTRATION = "INVALID", "ORCHESTRATION_FAILURE"


def ci_status(out_dir: Path, exit_code: int) -> dict[str, Any]:
    """Distinguish C PASS / C FAIL with valid evidence / C INVALID / CI or orchestration failure.

    PASS and FAIL require a parseable evidence artifact whose run_status and verdict agree with the exit code.
    Anything else (missing or unparseable artifact, wrong schema, inconsistent exit code) is orchestration failure.
    """
    evidence = Path(out_dir) / "mv02c_evidence.json"
    base: dict[str, Any] = {"exit_code": exit_code, "evidence_present": evidence.is_file(), "evidence_sha256": None}
    if not evidence.is_file():
        return {**base, "status": C_STATUS_ORCHESTRATION, "reason": "evidence artifact missing"}
    base["evidence_sha256"] = sha256_file(evidence)
    try:
        document = json.loads(evidence.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {**base, "status": C_STATUS_ORCHESTRATION, "reason": f"evidence unparseable: {exc}"}
    if document.get("schema") != EVIDENCE_SCHEMA:
        return {**base, "status": C_STATUS_ORCHESTRATION, "reason": "unexpected evidence schema"}
    run_status, verdict = document.get("run_status"), document.get("c_verdict")
    if exit_code == EXIT_PASS and run_status == VALID and verdict == PASS:
        return {**base, "status": C_STATUS_PASS}
    if exit_code == EXIT_FAIL and run_status == VALID and verdict == FAIL:
        return {**base, "status": C_STATUS_FAIL}
    if exit_code == EXIT_INVALID and run_status == INVALID and verdict is None:
        return {**base, "status": C_STATUS_INVALID}
    return {**base, "status": C_STATUS_ORCHESTRATION,
            "reason": f"exit code {exit_code} inconsistent with run_status={run_status} verdict={verdict}"}


def _main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="MV-02C C1-C10 against frozen resource_monitor_v1 (CI only)")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--classify-exit-code", type=int,
                        help="do not execute; classify an existing evidence directory and the suite's exit code")
    args = parser.parse_args(argv)
    if args.classify_exit_code is not None:
        status = ci_status(args.out_dir, args.classify_exit_code)
        (args.out_dir / "mv02c_status.json").write_bytes(serialize(status))
        print(f"C_STATUS={status['status']}")
        print(f"C_EVIDENCE_SHA256={status['evidence_sha256']}")
        return 0
    if os.environ.get("CI") != "true" or os.environ.get("GITHUB_ACTIONS") != "true":
        print("MV02C-REFUSED: the complete C1-C10 suite runs only on GitHub Actions (CI=true, GITHUB_ACTIONS=true)")
        return EXIT_REFUSED
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mv02c-") as scratch:
        records, provenance = run_suite(Path(scratch))
    evidence = build_evidence(records, commit_sha=os.environ.get("GITHUB_SHA"))
    (args.out_dir / "mv02c_evidence.json").write_bytes(serialize(evidence))
    (args.out_dir / "mv02c_evidence_provenance.json").write_bytes(serialize(
        {"schema": PROVENANCE_SCHEMA, "platform": platform.platform(), "python": sys.version, "cases": provenance}))
    print(f"MV02C-RUN-STATUS: {evidence['run_status']}")
    print(f"MV02C-VERDICT: {evidence['c_verdict']}")
    for record in records:
        print(f"MV02C-CASE: {record['case_id']} classification={record.get('classification')} "
              f"match={record.get('match')} status={record['run_status']}")
    if evidence["run_status"] != VALID:
        return EXIT_INVALID
    return EXIT_PASS if evidence["c_verdict"] == PASS else EXIT_FAIL


def main(argv: Sequence[str]) -> int:
    try:
        return _main(argv)
    except SystemExit:
        raise
    except BaseException:  # orchestration failure: distinct exit code, never confused with a C FAIL
        traceback.print_exc()
        return EXIT_ORCHESTRATION


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
