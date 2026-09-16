"""Fast structural checks for the MNT-09 mutation definitions (the full runner is a manual command)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import taxonomy_population_registry_v1_mutations as mnt09m  # noqa: E402


def test_every_mutation_anchor_occurs_exactly_once_and_mutant_compiles():
    source = mnt09m.SOURCE.read_text(encoding="utf-8")
    for mutation in mnt09m.MUTATIONS:
        mutated = mnt09m.mutated_source(mutation)
        assert mutated != source, mutation["name"]
        compile(mutated, str(mnt09m.SOURCE), "exec")


def test_mutation_definitions_are_well_formed():
    names = [m["name"] for m in mnt09m.MUTATIONS]
    assert len(names) == len(set(names))
    caught = {m["name"] for m in mnt09m.MUTATIONS if m["expected"] == "caught"}
    for mutation in mnt09m.MUTATIONS:
        assert mutation["expected"] in ("caught", "equivalent")
        if mutation["expected"] == "equivalent":
            assert mutation.get("proven_by") in caught and mutation.get("reason")


def test_every_admission_rule_has_at_least_one_caught_mutation():
    caught = {m["name"] for m in mnt09m.MUTATIONS if m["expected"] == "caught"}
    for rule in ("a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9", "a10", "a11"):
        assert any(name.startswith(f"{rule}_") for name in caught), f"rule {rule.upper()} has no caught mutation"


def test_heldout_firewall_mutations_are_present_and_caught():
    caught = {m["name"] for m in mnt09m.MUTATIONS if m["expected"] == "caught"}
    assert {"a5_split_check_removed", "a5_permitted_splits_widened_to_heldout"} <= caught


def test_required_protections_are_present():
    names = {m["name"] for m in mnt09m.MUTATIONS}
    required = {
        "a2_disk_hash_check_removed", "a2_partial_methodology_set_allowed", "a3_accepts_truthiness",
        "a4_condition_resolution_removed", "a5_split_check_removed",
        "a5_permitted_splits_widened_to_heldout", "a6_contract_enforced_after_gate_match",
        "a7_per_arm_count_check_removed", "a8_task_set_check_removed", "a9_gate_sha_ignored",
        "a9_family_filter_removed", "a10_selection_branches_on_model",
        "a11_outcome_fields_permitted_for_future", "historical_assertion_check_removed",
    }
    assert required <= names


def test_status_channel_never_reports_infrastructure_as_a_kill():
    source = Path(mnt09m.__file__).read_text(encoding="utf-8")
    assert "anchor_error" in source and "mutation_load_error" in source
    assert "child_error" in source and "pytest_error" in source
    assert mnt09m.STATUS_PREFIX == "MNT09-STATUS:"


def test_namespace_package_loader_registers_parent_attribute():
    import benchmark.analysis
    import benchmark.analysis.taxonomy_population_registry_v1 as original

    try:
        module = mnt09m.load_mutated_module(
            next(m for m in mnt09m.MUTATIONS if m["name"] == "a5_permitted_splits_widened_to_heldout"))
        assert module is not original
        assert sys.modules[mnt09m.MODULE] is module
        assert benchmark.analysis.taxonomy_population_registry_v1 is module
    finally:
        sys.modules[mnt09m.MODULE] = original
        benchmark.analysis.taxonomy_population_registry_v1 = original
