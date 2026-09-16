"""Reproducible mutation checks for the S2 paired-substrate module and Stage-1 classifier.

Each mutation replaces one exact anchor in `benchmark/analysis/paired_substrate_v1.py` in memory
(the file on disk is never modified; no frozen MNT-07/MNT-08/MNT-09 artifact is ever touched) and
runs `tests/test_paired_substrate_v1.py` plus the ownership-boundary suite against the mutated
module.

Expected status:
  caught      the synthetic suites must fail
  equivalent  the suites are expected to pass; `proven_by` names a caught mutation demonstrating the
              protected property

Status travels over a runner-owned channel, never inferred from an exit code alone: an anchor error,
a load error, a pytest infrastructure error or a dead child is infrastructure and is never counted
as a mutation kill.

Usage (manual; the fast structural subset runs in CI):
  python benchmark/analysis/paired_substrate_v1_mutations.py
  python benchmark/analysis/paired_substrate_v1_mutations.py --only NAME
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "benchmark" / "analysis" / "paired_substrate_v1.py"
SUITES = ("tests/test_paired_substrate_v1.py", "tests/test_paired_substrate_mnt09_boundary.py")
MODULE = "benchmark.analysis.paired_substrate_v1"

MUTATIONS: list[dict[str, str]] = [
    # --- ownership boundary: MNT-09 is the only admission authority
    {"name": "boundary_accepts_non_admission_input", "expected": "caught",
     "old": "    _require(isinstance(admission, mnt09.Admission),\n"
            "             \"population input must be a taxonomy_population_registry_v1.Admission; this module does \"\n"
            "             \"not admit populations and never accepts raw rows\")\n",
     "new": ""},
    {"name": "boundary_accepts_duck_typed_admission", "expected": "caught",
     "old": "    _require(isinstance(admission, mnt09.Admission),",
     "new": "    _require(hasattr(admission, \"selection\") or isinstance(admission, mnt09.Admission),"},
    {"name": "boundary_split_defence_removed", "expected": "caught",
     "old": "            _require(row.get(\"split\") == \"dev\",\n"
            "                     f\"{side.arm_id}/{task}: split {row.get('split')!r} is not dev\")\n",
     "new": "            pass\n"},

    # --- fail-closed compatibility
    {"name": "task_set_mismatch_permitted", "expected": "caught",
     "old": "    _require(set(incumbent.rows) == set(challenger.rows),",
     "new": "    _require(True or set(incumbent.rows) == set(challenger.rows),"},
    {"name": "condition_envelope_mismatch_permitted", "expected": "caught",
     "old": "    _require(not differing,\n"
            "             \"condition envelopes differ in a non-model key; the comparison is not model-only. \"\n"
            "             f\"differing keys: {differing}\")\n",
     "new": ""},
    {"name": "corpus_identity_mismatch_permitted", "expected": "caught",
     "old": "        _require(_gate(inc, \"corpus_sha256\") == _gate(chal, \"corpus_sha256\"),\n"
            "                 f\"{task}: oracle/corpus identity differs between arms\")\n",
     "new": ""},
    {"name": "uncertified_harness_difference_permitted", "expected": "caught",
     "old": "        except hdc.HarnessDeltaError as exc:\n"
            "            raise PairedError(f\"{task}: {exc}\") from exc\n",
     "new": "        except hdc.HarnessDeltaError:\n"
            "            certificate = None\n"},
    {"name": "missing_taxonomy_permitted", "expected": "caught",
     "old": "                _require(side[\"taxonomy\"] is not None,\n"
            "                         f\"{arm}/{task}: unsuccessful solvable trajectory has no frozen-taxonomy \"\n"
            "                         \"classification; the comparison cannot be completed\")\n",
     "new": "                pass\n"},
    {"name": "duplicate_task_in_selection_permitted", "expected": "equivalent",
     "proven_by": "task_set_mismatch_permitted",
     "reason": "Redundant against MNT-09's own A8 duplicate-task rule: an Admission cannot contain two "
               "rows for one task in one arm, so this assertion is unreachable through the supported "
               "entry point. It is retained because ArmSelection is also constructed directly in tests "
               "and would otherwise silently overwrite a row.",
     "old": "        _require(task not in rows, f\"{arm_id}: duplicate task {task!r} in an admitted selection\")\n",
     "new": ""},

    {"name": "same_arm_comparison_permitted", "expected": "caught",
     "old": "    _require(incumbent_arm != challenger_arm,\n",
     "new": "    _require(True or incumbent_arm != challenger_arm,\n"},

    # --- UNKNOWN safety evidence must never become zero events
    {"name": "out_of_scope_unknown_becomes_zero", "expected": "caught",
     "old": "    mutated = row.get(\"files_mutated\", _MISSING)\n"
            "    if mutated is _MISSING or not isinstance(mutated, list):\n"
            "        return UNKNOWN\n",
     "new": "    mutated = row.get(\"files_mutated\") or []\n"},
    {"name": "unresolvable_gold_set_becomes_zero", "expected": "caught",
     "old": "    if gold is None:\n        return UNKNOWN\n",
     "new": "    if gold is None:\n        return 0\n"},
    {"name": "empty_mutation_list_becomes_unknown", "expected": "caught",
     "old": "    gold_set = {_normalize_path(g) for g in gold}\n"
            "    return sum(1 for path in mutated if _normalize_path(path) not in gold_set)",
     "new": "    if not mutated:\n        return UNKNOWN\n"
            "    gold_set = {_normalize_path(g) for g in gold}\n"
            "    return sum(1 for path in mutated if _normalize_path(path) not in gold_set)"},
    {"name": "unknown_dimension_counted_in_the_regression", "expected": "caught",
     "old": "            totals[\"incumbent\"][key] = UNKNOWN\n"
            "            totals[\"challenger\"][key] = UNKNOWN\n"
            "            continue\n",
     "new": "            totals[\"incumbent\"][key] = 0\n"
            "            totals[\"challenger\"][key] = 0\n"},
    {"name": "stage1_unknown_safety_gate_removed", "expected": "caught",
     "old": "    elif inputs[\"safety_evidence_incomplete\"]:\n",
     "new": "    elif False and inputs[\"safety_evidence_incomplete\"]:\n"},
    {"name": "stage1_unknown_safety_treated_as_observed_harm", "expected": "caught",
     "old": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"] or not inputs[\"interface_viable\"]:\n"
            "        outcome, rule = CHALLENGER_NOT_VIABLE, 1\n",
     "new": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"] \\\n"
            "            or inputs[\"safety_evidence_incomplete\"] or not inputs[\"interface_viable\"]:\n"
            "        outcome, rule = CHALLENGER_NOT_VIABLE, 1\n"},
    {"name": "stage1_unknown_gate_placed_before_negative_outcomes", "expected": "caught",
     "old": "    elif inputs[\"separates_for_incumbent\"] or (c == 0 and b >= CLEARLY_UNPROMISING_MIN_B):\n"
            "        outcome, rule = CLEARLY_UNPROMISING, 2\n"
            "    elif inputs[\"safety_evidence_incomplete\"]:\n",
     "new": "    elif inputs[\"safety_evidence_incomplete\"]:\n"
            "        outcome, rule = SAFETY_EVIDENCE_INCOMPLETE, 2.5\n"
            "    elif inputs[\"separates_for_incumbent\"] or (c == 0 and b >= CLEARLY_UNPROMISING_MIN_B):\n"
            "        outcome, rule = CLEARLY_UNPROMISING, 2\n"
            "    elif False:\n"},

    # --- exact McNemar
    {"name": "mcnemar_zero_discordant_reports_p_one", "expected": "caught",
     "old": "    if n == 0:\n        return {\"b\": b, \"c\": c, \"discordant\": 0, \"p_two_sided\": None,",
     "new": "    if n == 0:\n        return {\"b\": b, \"c\": c, \"discordant\": 0, \"p_two_sided\": 1.0,"},
    {"name": "mcnemar_uses_max_instead_of_min", "expected": "caught",
     "old": "    low = min(b, c)", "new": "    low = max(b, c)"},
    {"name": "mcnemar_drops_the_two_sided_doubling", "expected": "caught",
     "old": "    two_sided = min(1.0, 2 * _binom_tail_le(low, n))",
     "new": "    two_sided = min(1.0, _binom_tail_le(low, n))"},
    {"name": "mcnemar_direction_swapped", "expected": "caught",
     "old": "    p_challenger = _binom_tail_le(b, n)   # small b favours the challenger\n"
            "    p_incumbent = _binom_tail_le(c, n)\n",
     "new": "    p_challenger = _binom_tail_le(c, n)\n    p_incumbent = _binom_tail_le(b, n)\n"},
    {"name": "separation_alpha_loosened", "expected": "caught",
     "old": "SEPARATION_ALPHA = 0.05                     # [POLICY]",
     "new": "SEPARATION_ALPHA = 0.10                     # [POLICY]"},

    # --- Stage-1 precedence and rules
    {"name": "stage1_viability_no_longer_dominates", "expected": "caught",
     "old": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"] or not inputs[\"interface_viable\"]:\n"
            "        outcome, rule = CHALLENGER_NOT_VIABLE, 1\n",
     "new": "    if False:\n        outcome, rule = CHALLENGER_NOT_VIABLE, 1\n"},
    {"name": "stage1_ignores_safety_regression", "expected": "caught",
     "old": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"] or not inputs[\"interface_viable\"]:",
     "new": "    if not inputs[\"resource_viable\"] or not inputs[\"interface_viable\"]:"},
    {"name": "stage1_ignores_interface_viability", "expected": "caught",
     "old": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"] or not inputs[\"interface_viable\"]:",
     "new": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"]:"},
    {"name": "stage1_ignores_resource_viability", "expected": "caught",
     "old": "    if not inputs[\"resource_viable\"] or inputs[\"safety_regression\"] or not inputs[\"interface_viable\"]:",
     "new": "    if inputs[\"safety_regression\"] or not inputs[\"interface_viable\"]:"},
    {"name": "stage1_clearly_unpromising_rule_removed", "expected": "caught",
     "old": "    elif inputs[\"separates_for_incumbent\"] or (c == 0 and b >= CLEARLY_UNPROMISING_MIN_B):\n"
            "        outcome, rule = CLEARLY_UNPROMISING, 2\n",
     "new": ""},
    {"name": "stage1_complementarity_before_viability", "expected": "caught",
     "old": "    single_agent_signal = inputs[\"separates_for_challenger\"] or c > b\n"
            "    if not inputs[\"resource_viable\"]",
     "new": "    single_agent_signal = inputs[\"separates_for_challenger\"] or c > b\n"
            "    if b >= BIDIRECTIONAL_MIN_UNIQUE and c >= BIDIRECTIONAL_MIN_UNIQUE:\n"
            "        outcome, rule = COMPLEMENTARITY_CANDIDATE, 3\n"
            "    elif not inputs[\"resource_viable\"]"},
    {"name": "stage1_bidirectional_threshold_lowered", "expected": "caught",
     "old": "BIDIRECTIONAL_MIN_UNIQUE = 2                # [POLICY]",
     "new": "BIDIRECTIONAL_MIN_UNIQUE = 1                # [POLICY]"},
    {"name": "stage1_weak_screen_removed", "expected": "caught",
     "old": "    elif single_agent_signal:\n        outcome, rule = PROMISING_SINGLE_AGENT, 4\n",
     "new": ""},
    {"name": "stage1_stage_rule_needs_only_one_direction", "expected": "caught",
     "old": "    elif (inputs[\"stage_forward_challenger\"] >= STAGE_FORWARD_MIN\n"
            "          and inputs[\"stage_forward_incumbent\"] >= STAGE_FORWARD_MIN):",
     "new": "    elif (inputs[\"stage_forward_challenger\"] >= STAGE_FORWARD_MIN\n"
            "          or inputs[\"stage_forward_incumbent\"] >= STAGE_FORWARD_MIN):"},
    {"name": "stage1_clearly_unpromising_min_b_lowered", "expected": "caught",
     "old": "CLEARLY_UNPROMISING_MIN_B = 3               # [POLICY]",
     "new": "CLEARLY_UNPROMISING_MIN_B = 2               # [POLICY]"},

    # --- telemetry discipline
    {"name": "completion_tokens_defaults_to_zero", "expected": "caught",
     "old": "        vector[field] = row[field] if field in row else \"ABSENT\"",
     "new": "        vector[field] = row.get(field, 0)"},

    # --- safety / interface aggregates
    {"name": "safety_regression_requires_all_dimensions", "expected": "caught",
     "old": "    worse = sorted(key for key in comparable\n"
            "                   if totals[\"challenger\"][key] > totals[\"incumbent\"][key])",
     "new": "    worse = sorted(key for key in comparable\n"
            "                   if totals[\"challenger\"][key] > totals[\"incumbent\"][key] + 100)"},
    {"name": "interface_floor_ignores_tasks_with_an_action", "expected": "caught",
     "old": "    viable = chal_invalid <= ceiling and tasks_with_action >= MIN_TASKS_WITH_A_VALID_ACTION",
     "new": "    viable = chal_invalid <= ceiling"},
]


class AnchorError(RuntimeError):
    """The mutation's anchor no longer matches the source exactly once - the mutation never ran."""


def mutated_source(mutation: dict[str, str]) -> str:
    source = SOURCE.read_text(encoding="utf-8")
    if source.count(mutation["old"]) != 1:
        raise AnchorError(
            f"anchor for {mutation['name']} occurs {source.count(mutation['old'])} times; expected exactly 1")
    return source.replace(mutation["old"], mutation["new"])


def load_mutated_module(mutation: dict[str, str]):
    sys.path.insert(0, str(ROOT))
    import benchmark.analysis  # noqa: F401

    spec = importlib.util.spec_from_loader(MODULE, loader=None, origin=str(SOURCE))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(SOURCE)
    sys.modules[MODULE] = module
    exec(compile(mutated_source(mutation), str(SOURCE), "exec"), module.__dict__)
    sys.modules["benchmark.analysis"].paired_substrate_v1 = module
    return module


STATUS_PREFIX = "PSV1-STATUS:"   # runner-owned channel: the parent never infers status from an exit code


def _child(name: str) -> int:
    import pytest

    mutation = next(m for m in MUTATIONS if m["name"] == name)
    try:
        load_mutated_module(mutation)
    except AnchorError as exc:
        print(f"{STATUS_PREFIX} anchor_error {exc}")
        return 3
    except Exception as exc:
        print(f"{STATUS_PREFIX} mutation_load_error {type(exc).__name__}: {exc}")
        return 4
    basetemp = Path(os.environ.get("PSV1_BASETEMP") or os.environ.get("TEMP", "/tmp")) / f"psv1_mutation_{name}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    code = int(pytest.main(["-q", "-p", "no:cacheprovider", "-W", "ignore",
                            "--basetemp", str(basetemp), *SUITES]))
    status = {0: "survived", 1: "caught"}.get(code, f"pytest_error(exit {code})")
    print(f"{STATUS_PREFIX} {status}")
    return code


def run(only: str | None = None) -> int:
    violations = 0
    for mutation in MUTATIONS:
        if only and mutation["name"] != only:
            continue
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mutation["name"]],
                              cwd=ROOT, capture_output=True, text=True,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        reported = next((line[len(STATUS_PREFIX):].strip() for line in proc.stdout.splitlines()
                         if line.startswith(STATUS_PREFIX)), None)
        if reported is None:
            observed = f"child_error(exit {proc.returncode})"
        elif reported == "caught":
            observed = "caught"
        elif reported == "survived":
            observed = "equivalent"
        else:
            observed = reported.split()[0]
        summary = next((line for line in reversed(proc.stdout.splitlines())
                        if " passed" in line or " failed" in line or " error" in line), "")
        ok = observed == mutation["expected"]
        violations += 0 if ok else 1
        print(f"{'OK ' if ok else 'BAD'} {mutation['name']}: expected {mutation['expected']}, "
              f"observed {observed} ({summary.strip()})")
    print(f"mutations: {'OK' if violations == 0 else f'{violations} violation(s)'}")
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(_child(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--only":
        raise SystemExit(run(sys.argv[2]))
    raise SystemExit(run())
