"""Reproducible mutation checks for MV-02 (mutation-testing skill; follows paired_substrate_v1_mutations).

Each mutation replaces one exact anchor in memory (files on disk are never modified) and runs the protecting
suites in a child process. Status travels over a runner-owned channel: an anchor error, a load error, a pytest
infrastructure error or a dead child is infrastructure and is never counted as a kill.

Two groups:
  local   MV-02 modules, protected by the injected/fake test suites
  v1      the frozen resource_monitor_v1, mutated IN MEMORY ONLY, protected by the real MV-02C case it targets.
          Runs only on GitHub Actions: executing C cases against (mutated) v1 is CI-only by the approved plan.
          caught = the targeted case's record does not match its preregistered expectation.

Usage:
  python scripts/monitor_validity_v2/mutations.py --group local
  python scripts/monitor_validity_v2/mutations.py --group v1        (CI only)
  python scripts/monitor_validity_v2/mutations.py --only NAME
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "scripts" / "monitor_validity_v2"
STATUS_PREFIX = "MV02-MUT-STATUS:"

A_TESTS = ("tests/test_mv02a.py", "tests/test_mv02_vacuity.py", "tests/test_mv02_combined_reachability.py")
B_TESTS = ("tests/test_mv02b.py", "tests/test_mv02b_policy_isolation.py", "tests/test_mv02_combined_reachability.py")
C_TESTS = ("tests/test_mv02c_local.py", "tests/test_mv02_combined_reachability.py")
COMBINE_TESTS = ("tests/test_mv02_combined_reachability.py",)


def _m(name, module, file, old, new, suites, group="local", target_case=None):
    return {"name": name, "module": module, "file": file, "old": old, "new": new, "suites": suites,
            "group": group, "target_case": target_case, "expected": "caught"}


MUTATIONS: list[dict] = [
    # --- MV-02A
    _m("a_swap_monitored_and_unmonitored", "mv02a_perturbation", "mv02a_perturbation.py",
       'runner.monitored(command, timeout) if arm == "M" else', 'runner.monitored(command, timeout) if arm == "U" else',
       A_TESTS),
    _m("a_gate_on_wrapper_time", "mv02a_perturbation", "mv02a_perturbation.py",
       'relative = [(p["M"]["child_seconds"] - p["U"]["child_seconds"]) / baseline for p in run["pairs"]]',
       'relative = [(p["M"]["wrapper_seconds"] - p["U"]["wrapper_seconds"]) / baseline for p in run["pairs"]]',
       A_TESTS),
    _m("a_silently_drop_invalid_arms", "mv02a_perturbation", "mv02a_perturbation.py",
       '            elif pair[arm]["status"] != OK:\n', '            elif False:\n', A_TESTS),
    _m("a_zero_based_parity", "mv02a_perturbation", "mv02a_perturbation.py",
       'if pair_number % 2 == 1 else', 'if pair_number % 2 == 0 else', A_TESTS),
    _m("stats_non_strict_inclusion", "stats", "stats.py",
       "if -margin < low and high < margin:", "if -margin <= low and high <= margin:", ("tests/test_mv02_stats.py",)),
    # --- MV-02B
    _m("b_reference_omits_launcher", "mv02b_measurement", "mv02b_measurement.py",
       'ref = [r["self_ws"] + r["launcher_ws"] for r in refs', 'ref = [r["self_ws"] for r in refs', B_TESTS),
    _m("b_guard_band_zero", "mv02b_measurement", "mv02b_measurement.py",
       'guard = FROZEN_B["guard_band_s"]', "guard = 0.0", B_TESTS),
    _m("b_child_no_page_touch", "child_b_reference", "child_b_reference.py",
       "        block[offset] = 1\n", "        pass\n", B_TESTS),
    _m("b2_tolerance_is_t", "mv02b_measurement", "mv02b_measurement.py",
       'for p in adequate], FROZEN_B["b2_bytes"],', 'for p in adequate], FROZEN_B["t_bytes"],', B_TESTS),
    _m("b_x_reselected_every_invocation", "mv02b_measurement", "mv02b_measurement.py",
       "    if invocation == 1:\n        command +=", "    if True:\n        command +=", B_TESTS),
    _m("b_extra_invocation_added", "mv02b_measurement", "mv02b_measurement.py",
       'for invocation in range(1, FROZEN_B["invocations"] + 1):',
       'for invocation in range(1, FROZEN_B["invocations"] + 2):', B_TESTS),
    _m("b3_windows_cross_invocations", "mv02b_measurement", "mv02b_measurement.py",
       '        times = p["sample_times"]\n', '        times = [t for q in required for t in q["sample_times"]]\n',
       B_TESTS),
    _m("b_executor_accepts_policy_overrides", "mv02b_measurement", "mv02b_measurement.py",
       "            child_factory: ChildFactory | None = None) -> dict[str, Any]:",
       "            child_factory: ChildFactory | None = None, **overrides: Any) -> dict[str, Any]:", B_TESTS),
    # --- MV-02C (injected suites only)
    _m("c_accept_silent_death_with_gate_pass", "mv02c_enforcement", "mv02c_enforcement.py",
       "        if passed:\n            return SILENT_SAMPLER_DEATH_GATE_PASS\n",
       "        if passed:\n            return SILENT_SAMPLER_DEATH_GATE_FAIL\n", C_TESTS),
    _m("c_ignore_excepthook_records", "mv02c_enforcement", "mv02c_enforcement.py",
       'sampler_hooks = [h for h in hooks.records if h["sampler_thread"]]', "sampler_hooks = []", C_TESTS),
    _m("c_invalid_conditions_not_marked", "mv02c_enforcement", "mv02c_enforcement.py",
       'record["run_status"] = INVALID if invalid_reasons else VALID', 'record["run_status"] = VALID', C_TESTS),
    _m("c9_fault_at_call_3", "mv02c_enforcement", "mv02c_enforcement.py",
       "fault_call=5, expected=NOT_SILENT_PASS", "fault_call=3, expected=NOT_SILENT_PASS", C_TESTS),
    _m("c2_expected_gate_pass", "mv02c_enforcement", "mv02c_enforcement.py",
       "below=(1,), expected=_exact(SAFE_GATE_FAIL, abort=False, gate_passed=False, failed_condition=MIN_CONDITION)),",
       "below=(1,), expected=_exact(NOMINAL, abort=False, gate_passed=True)),", C_TESTS),
    # --- combine
    _m("combine_unresolved_as_qualified", "combine", "combine.py",
       '    elif UNRESOLVED in (verdicts["A"], verdicts["B"]):\n        verdict = UNRESOLVED\n',
       '    elif UNRESOLVED in (verdicts["A"], verdicts["B"]):\n        verdict = QUALIFIED\n', COMBINE_TESTS),
    _m("combine_invalid_as_unresolved", "combine", "combine.py",
       '        return {"run_status": INVALID, "verdict": None, "components": components}\n',
       '        return {"run_status": VALID, "verdict": UNRESOLVED, "components": components}\n', COMBINE_TESTS),
    _m("combine_c_fail_does_not_stop", "combine", "combine.py",
       'return c["run_status"] == VALID and c["c_verdict"] == PASS', 'return c["run_status"] == VALID',
       COMBINE_TESTS),
    # --- frozen v1, in memory only, CI only
    _m("v1_watchdog_streak_7", "resource_monitor_v1", "../resource_monitor_v1.py",
       "WATCHDOG_CONSECUTIVE_SAMPLES = 8", "WATCHDOG_CONSECUTIVE_SAMPLES = 7", (), group="v1", target_case="C3"),
    _m("v1_watchdog_boundary_le", "resource_monitor_v1", "../resource_monitor_v1.py",
       "run = run + 1 if sample.available_bytes < reserve_bytes else 0",
       "run = run + 1 if sample.available_bytes <= reserve_bytes else 0", (), group="v1", target_case="C6"),
    _m("v1_watchdog_streak_not_reset", "resource_monitor_v1", "../resource_monitor_v1.py",
       "run = run + 1 if sample.available_bytes < reserve_bytes else 0",
       "run = run + 1 if sample.available_bytes < reserve_bytes else run", (), group="v1", target_case="C5"),
]


class AnchorError(RuntimeError):
    """The mutation's anchor does not match the source exactly once - the mutation never ran."""


def source_path(mutation: dict) -> Path:
    return (PKG / mutation["file"]).resolve()


def mutated_source(mutation: dict) -> str:
    source = source_path(mutation).read_text(encoding="utf-8")
    count = source.count(mutation["old"])
    if count != 1:
        raise AnchorError(f"anchor for {mutation['name']} occurs {count} times; expected exactly 1")
    return source.replace(mutation["old"], mutation["new"])


def _load(mutation: dict, module_name: str):
    path = source_path(mutation)
    spec = importlib.util.spec_from_loader(module_name, loader=None, origin=str(path))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    sys.modules[module_name] = module
    exec(compile(mutated_source(mutation), str(path), "exec"), module.__dict__)
    return module


def _child_local(mutation: dict) -> int:
    import pytest

    sys.path.insert(0, str(ROOT))
    import scripts.monitor_validity_v2 as package

    try:
        module = _load(mutation, f"scripts.monitor_validity_v2.{mutation['module']}")
        setattr(package, mutation["module"], module)
    except AnchorError as exc:
        print(f"{STATUS_PREFIX} anchor_error {exc}")
        return 3
    except Exception as exc:
        print(f"{STATUS_PREFIX} mutation_load_error {type(exc).__name__}: {exc}")
        return 4
    basetemp = Path(os.environ.get("MV02_MUT_BASETEMP") or tempfile.gettempdir()) / f"mv02_mutation_{mutation['name']}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    code = int(pytest.main(["-q", "-p", "no:cacheprovider", "-W", "ignore", "--basetemp", str(basetemp),
                            *mutation["suites"]]))
    status = {0: "survived", 1: "caught"}.get(code, f"pytest_error(exit {code})")
    print(f"{STATUS_PREFIX} {status}")
    return code


def _child_v1(mutation: dict) -> int:
    sys.path.insert(0, str(ROOT))
    from scripts.monitor_validity_v2 import VALID
    from scripts.monitor_validity_v2 import mv02c_enforcement as mc

    try:
        mutant = _load(mutation, "mv02_mutant_resource_monitor_v1")
    except AnchorError as exc:
        print(f"{STATUS_PREFIX} anchor_error {exc}")
        return 3
    except Exception as exc:
        print(f"{STATUS_PREFIX} mutation_load_error {type(exc).__name__}: {exc}")
        return 4
    case = next(c for c in mc.CASES if c.case_id == mutation["target_case"])
    try:
        with tempfile.TemporaryDirectory(prefix="mv02-v1-mutant-") as scratch:
            record, _ = mc.run_case(case, Path(scratch), monitor=mutant)
    except Exception as exc:
        print(f"{STATUS_PREFIX} harness_error {type(exc).__name__}: {exc}")
        return 5
    if record["run_status"] != VALID:
        print(f"{STATUS_PREFIX} harness_error target case INVALID: {record['invalid_reasons']}")
        return 5
    print(f"{STATUS_PREFIX} {'survived' if record['match'] else 'caught'} "
          f"({case.case_id} classification={record['classification']} abort={record['watchdog']['abort']})")
    return 0 if record["match"] else 1


def on_github_actions() -> bool:
    return os.environ.get("CI") == "true" and os.environ.get("GITHUB_ACTIONS") == "true"


def run(group: str | None, only: str | None) -> int:
    selected = [m for m in MUTATIONS if (only is None or m["name"] == only) and (group is None or m["group"] == group)]
    if not selected:
        print("no mutation selected")
        return 2
    if any(m["group"] == "v1" for m in selected) and not on_github_actions():
        print("MV02-MUT-REFUSED: v1 mutations execute MV-02C cases and run only on GitHub Actions")
        return 5
    violations = 0
    for mutation in selected:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mutation["name"]],
                              cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        reported = next((line[len(STATUS_PREFIX):].strip() for line in proc.stdout.splitlines()
                         if line.startswith(STATUS_PREFIX)), None)
        if reported is None:
            observed = f"child_error(exit {proc.returncode})"
        else:
            observed = {"caught": "caught", "survived": "survived"}.get(reported.split()[0], reported.split()[0])
        detail = reported or proc.stderr.strip().splitlines()[-1:] or ""
        ok = observed == mutation["expected"]
        violations += 0 if ok else 1
        print(f"{'OK ' if ok else 'BAD'} {mutation['name']}: expected {mutation['expected']}, observed {observed} "
              f"({detail})")
    print(f"mutations: {'OK' if violations == 0 else f'{violations} violation(s)'}")
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        chosen = next(m for m in MUTATIONS if m["name"] == sys.argv[2])
        if chosen["group"] == "v1":
            if not on_github_actions():
                print("MV02-MUT-REFUSED: v1 mutations execute MV-02C cases and run only on GitHub Actions")
                raise SystemExit(5)
            raise SystemExit(_child_v1(chosen))
        raise SystemExit(_child_local(chosen))
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=("local", "v1"))
    parser.add_argument("--only")
    arguments = parser.parse_args()
    if arguments.group is None and arguments.only is None:
        arguments.group = "local"
    raise SystemExit(run(arguments.group, arguments.only))
