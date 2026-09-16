"""Reproducible mutation checks for MNT-09 (benchmark/analysis/taxonomy_population_applicability_v1.md).

Each mutation replaces one exact anchor in `benchmark/analysis/taxonomy_population_registry_v1.py` in memory (the
file on disk is never modified; no frozen MNT-07/MNT-08 artifact is ever touched) and runs
`tests/test_taxonomy_population_registry_v1.py` against the mutated module.

Expected status:
  caught      the synthetic suite must fail
  equivalent  the suite is expected to pass; `proven_by` names a caught mutation demonstrating the protected property

Status is reported over a runner-owned channel, never inferred from an exit code alone: an anchor error, a load
error, a pytest infrastructure error or a dead child is infrastructure and is never counted as a mutation kill.

Usage (manual; the fast structural subset runs in CI):
  python benchmark/analysis/taxonomy_population_registry_v1_mutations.py
  python benchmark/analysis/taxonomy_population_registry_v1_mutations.py --only NAME
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "benchmark" / "analysis" / "taxonomy_population_registry_v1.py"
SUITE = "tests/test_taxonomy_population_registry_v1.py"
MODULE = "benchmark.analysis.taxonomy_population_registry_v1"

MUTATIONS: list[dict[str, str]] = [
    # --- A2: frozen methodology identity
    {"name": "a2_disk_hash_check_removed", "expected": "caught",
     "old": "        actual = _sha256_file(rel)\n"
            "        _require(actual == expected, f\"A2: {rel} on disk {actual} != frozen {expected}\")\n",
     "new": ""},
    {"name": "a2_declared_hash_check_removed", "expected": "caught",
     "old": "        _require(declared[rel] == expected, f\"A2: {rel} declared {declared[rel]} != frozen {expected}\")\n",
     "new": ""},
    {"name": "a2_partial_methodology_set_allowed", "expected": "caught",
     "old": "    _require(set(declared) == set(frozen),",
     "new": "    _require(set(declared) <= set(frozen),"},

    # --- A3: explicit authorization, identity not truthiness
    {"name": "a3_accepts_truthiness", "expected": "caught",
     "old": "    _require(new_data_application is True or new_data_application is False,\n"
            "             \"PRR: new_data_application must be literally True or False\")",
     "new": "    _require(bool(new_data_application) or new_data_application is False,\n"
            "             \"PRR: new_data_application must be literally True or False\")"},

    # --- A4: condition-resolution contract
    {"name": "a4_condition_resolution_removed", "expected": "caught",
     "old": "        _require(isinstance(entry, Mapping),\n"
            "                 f\"A4: {arm.arm_id}: condition {arm.condition!r} is not defined in CONDITIONS\")\n"
            "        _require(isinstance(entry.get(\"overrides\"), Mapping),\n"
            "                 f\"A4: {arm.arm_id}: condition {arm.condition!r} has no overrides mapping\")\n",
     "new": "        if not isinstance(entry, Mapping):\n            continue\n"},
    {"name": "a4_overrides_check_removed", "expected": "caught",
     "old": "        _require(isinstance(entry.get(\"overrides\"), Mapping),\n"
            "                 f\"A4: {arm.arm_id}: condition {arm.condition!r} has no overrides mapping\")\n",
     "new": ""},

    # --- A5: heldout firewall
    {"name": "a5_split_check_removed", "expected": "caught",
     "old": "        _require(arm.split in PERMITTED_SPLITS,",
     "new": "        _require(True or arm.split in PERMITTED_SPLITS,"},
    {"name": "a5_permitted_splits_widened_to_heldout", "expected": "caught",
     "old": "PERMITTED_SPLITS: frozenset[str] = frozenset({\"dev\"})",
     "new": "PERMITTED_SPLITS: frozenset[str] = frozenset({\"dev\", \"heldout\"})"},

    # --- A6: row contract, and the position at which it is enforced
    {"name": "a6_calls_list_check_removed", "expected": "caught",
     "old": "    _require(isinstance(calls, list), f\"{where}: calls must be a list\")\n",
     "new": ""},
    {"name": "a6_call_mapping_check_removed", "expected": "caught",
     "old": "    _require(all(isinstance(call, Mapping) for call in calls), f\"{where}: every call must be a mapping\")\n",
     "new": ""},
    {"name": "a6_fingerprint_check_removed", "expected": "caught",
     "old": "    _require(isinstance(row.get(\"fingerprint\"), str) and row[\"fingerprint\"],\n"
            "             f\"{where}: fingerprint must be a non-empty string\")\n",
     "new": ""},
    {"name": "a6_required_keys_check_removed", "expected": "caught",
     "old": "    missing = [key for key in REQUIRED_ROW_KEYS if key not in row]\n"
            "    _require(not missing, f\"{where}: missing key(s) {missing}\")\n",
     "new": ""},
    {"name": "a6_contract_enforced_after_gate_match", "expected": "caught",
     # The original defect this fix closed: a row with a malformed `experiment` produces no gate sha, so it
     # silently dropped out of selection instead of failing loudly.
     "old": "        candidate_arms = [arm for arm in prr.arms if (arm.split, arm.condition) == family]\n"
            "        check_row_contract(candidate_arms[0].arm_id, number, row)\n",
     "new": "        candidate_arms = [arm for arm in prr.arms if (arm.split, arm.condition) == family]\n"},

    # --- A7: structural counts
    {"name": "a7_per_arm_count_check_removed", "expected": "caught",
     "old": "        _require(len(arm_rows) == prr.expected_rows_per_arm,\n"
            "                 f\"A7: {arm.arm_id}: {len(arm_rows)} rows selected, expected {prr.expected_rows_per_arm}\")\n",
     "new": ""},
    {"name": "a7_total_count_check_removed", "expected": "equivalent",
     "proven_by": "a7_per_arm_count_check_removed",
     "reason": "Redundant given the per-arm check plus load_prr's invariant expected_total_rows == "
               "expected_rows_per_arm * len(arms): if every arm holds exactly expected_rows_per_arm rows then the "
               "total is necessarily expected_total_rows. Retained as defence in depth, and it would become "
               "load-bearing if the per-arm rule were ever relaxed.",
     "old": "    _require(total_rows == prr.expected_total_rows,\n"
            "             f\"A7: {total_rows} rows selected in total, expected {prr.expected_total_rows}\")\n",
     "new": ""},

    # --- A8: task membership
    {"name": "a8_task_set_check_removed", "expected": "caught",
     "old": "        _require(set(tasks) == set(prr.task_set), f\"A8: {arm.arm_id}: task set differs from the declared task_set\")\n",
     "new": ""},
    {"name": "a8_duplicate_task_check_removed", "expected": "equivalent",
     "proven_by": "a8_task_set_check_removed",
     "reason": "Redundant against the conjunction of the A7 per-arm count and the A8 task-set equality: with a fixed "
               "row count equal to the declared task-set size, a duplicated task forces a missing task, so the set "
               "comparison already fails. It is kept because it names the actual defect ('duplicate task rows') "
               "rather than reporting a set difference, and it stays load-bearing for any future population whose "
               "row count may exceed its task-set size.",
     "old": "        _require(len(set(tasks)) == len(tasks), f\"A8: {arm.arm_id}: duplicate task rows\")\n",
     "new": ""},

    # --- A9: gate discrimination / unregistered arms stay invisible
    {"name": "a9_gate_sha_ignored", "expected": "caught",
     "old": "            if _row_gate(row) == arm.gate_sha256:\n"
            "                selected[arm.arm_id].append((number, row))\n",
     "new": "            selected[arm.arm_id].append((number, row))\n"},
    {"name": "a9_family_filter_removed", "expected": "caught",
     "old": "        if family not in families:\n            continue\n",
     "new": ""},

    # --- A10: model identity is provenance only
    {"name": "a10_selection_branches_on_model", "expected": "caught",
     "old": "        family = (row.get(\"split\"), row.get(\"condition\"))",
     "new": "        family = (row.get(\"split\"), row.get(\"condition\")) "
            "if row.get(\"model\") != \"omega:99b\" else (None, None)"},

    # --- A11: preregistered structure vs observed outcome
    {"name": "a11_outcome_fields_permitted_for_future", "expected": "caught",
     "old": "    if obj.get(\"new_data_application\") is True:\n"
            "        declared_outcomes = sorted(set(obj) & set(OUTCOME_DEPENDENT_FIELDS))\n"
            "        _require(not declared_outcomes,\n"
            "                 f\"A11: outcome-dependent field(s) {declared_outcomes} may not be preregistered \"\n"
            "                 f\"for new-data application\")\n",
     "new": ""},
    {"name": "a11_historical_assertions_allowed_for_future", "expected": "equivalent",
     "proven_by": "a11_outcome_fields_permitted_for_future",
     "reason": "Redundant because `historical_assertions` is itself a member of OUTCOME_DEPENDENT_FIELDS, so the "
               "early A11 rule already refuses it for any record with new_data_application is True, and that is the "
               "only case this guard could reject (a historical record satisfies `new_data_application is False` by "
               "construction). Retained as defence in depth and as local documentation at the point of use.",
     "old": "        _require(new_data_application is False,\n"
            "                 \"PRR: historical_assertions is permitted only for a historical population\")\n",
     "new": ""},
    {"name": "historical_assertion_check_removed", "expected": "caught",
     "old": "        if \"unsuccessful_solvable\" in expectations:\n"
            "            _require(observed_unsuccessful == expectations[\"unsuccessful_solvable\"],",
     "new": "        if \"unsuccessful_solvable\" in expectations:\n"
            "            _require(True or observed_unsuccessful == expectations[\"unsuccessful_solvable\"],"},

    # --- structural typing
    {"name": "int_field_accepts_bool", "expected": "caught",
     "old": "    _require(type(value) is int and value > 0, f\"{where}: {key} must be a positive int\")",
     "new": "    _require(isinstance(value, int) and value > 0, f\"{where}: {key} must be a positive int\")"},
    {"name": "unknown_prr_field_permitted", "expected": "caught",
     "old": "    _require(not unknown, f\"PRR: unknown field(s) {unknown}\")\n",
     "new": ""},
    {"name": "duplicate_selection_triple_permitted", "expected": "caught",
     "old": "    _require(len(set(triples)) == len(triples),\n"
            "             \"PRR: two arms share a (split, condition, gate_sha256) selection triple\")\n",
     "new": ""},
    {"name": "duplicate_arm_id_permitted", "expected": "caught",
     "old": "    _require(len(set(arm_ids)) == len(arm_ids), \"PRR: duplicate arm_id\")\n",
     "new": ""},
    {"name": "task_set_size_consistency_removed", "expected": "caught",
     "old": "    _require(expected_rows_per_arm == len(task_set),\n"
            "             \"PRR: expected_rows_per_arm must equal the declared task_set size\")\n",
     "new": ""},
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
    """`benchmark.analysis` is a namespace package here, so the child module must be registered in
    sys.modules and set as an attribute of the parent."""
    sys.path.insert(0, str(ROOT))
    import benchmark.analysis  # noqa: F401

    spec = importlib.util.spec_from_loader(MODULE, loader=None, origin=str(SOURCE))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(SOURCE)
    sys.modules[MODULE] = module
    exec(compile(mutated_source(mutation), str(SOURCE), "exec"), module.__dict__)
    sys.modules["benchmark.analysis"].taxonomy_population_registry_v1 = module
    return module


STATUS_PREFIX = "MNT09-STATUS:"   # runner-owned channel: the parent never infers status from an exit code alone


def _child(name: str) -> int:
    import pytest

    mutation = next(m for m in MUTATIONS if m["name"] == name)
    try:
        load_mutated_module(mutation)
    except AnchorError as exc:
        print(f"{STATUS_PREFIX} anchor_error {exc}")
        return 3
    except Exception as exc:  # the mutated source did not even import
        print(f"{STATUS_PREFIX} mutation_load_error {type(exc).__name__}: {exc}")
        return 4
    basetemp = Path(os.environ.get("MNT09_BASETEMP") or os.environ.get("TEMP", "/tmp")) / f"mnt09_mutation_{name}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    code = int(pytest.main(["-q", "-p", "no:cacheprovider", "-W", "ignore", "--basetemp", str(basetemp), SUITE]))
    # pytest: 0 all passed, 1 tests failed, 2 interrupted, 3 internal error, 4 usage error, 5 no tests collected.
    status = {0: "survived", 1: "caught"}.get(code, f"pytest_error(exit {code})")
    print(f"{STATUS_PREFIX} {status}")
    return code


def run(only: str | None = None) -> int:
    violations = 0
    for mutation in MUTATIONS:
        if only and mutation["name"] != only:
            continue
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mutation["name"]], cwd=ROOT,
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        reported = next((line[len(STATUS_PREFIX):].strip() for line in proc.stdout.splitlines()
                         if line.startswith(STATUS_PREFIX)), None)
        if reported is None:
            # No status line: the child died before it could report. Never a kill.
            observed = f"child_error(exit {proc.returncode})"
        elif reported == "caught":
            observed = "caught"
        elif reported == "survived":
            observed = "equivalent"
        else:
            # anchor_error, mutation_load_error, pytest_error(...): infrastructure, never a mutation kill
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
