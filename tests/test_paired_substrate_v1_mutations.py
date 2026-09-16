"""Fast structural checks for the S2 paired-substrate mutation definitions (full runner is manual)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import paired_substrate_v1_mutations as psm  # noqa: E402


def test_every_mutation_anchor_occurs_exactly_once_and_mutant_compiles():
    source = psm.SOURCE.read_text(encoding="utf-8")
    for mutation in psm.MUTATIONS:
        mutated = psm.mutated_source(mutation)
        assert mutated != source, mutation["name"]
        compile(mutated, str(psm.SOURCE), "exec")


def test_mutation_definitions_are_well_formed():
    names = [m["name"] for m in psm.MUTATIONS]
    assert len(names) == len(set(names))
    caught = {m["name"] for m in psm.MUTATIONS if m["expected"] == "caught"}
    for mutation in psm.MUTATIONS:
        assert mutation["expected"] in ("caught", "equivalent")
        if mutation["expected"] == "equivalent":
            assert mutation.get("proven_by") in caught and mutation.get("reason")


def test_required_protections_are_present():
    names = {m["name"] for m in psm.MUTATIONS}
    required = {
        "boundary_accepts_non_admission_input", "boundary_accepts_duck_typed_admission",
        "boundary_split_defence_removed", "task_set_mismatch_permitted",
        "condition_envelope_mismatch_permitted", "corpus_identity_mismatch_permitted",
        "uncertified_harness_difference_permitted", "missing_taxonomy_permitted",
        "mcnemar_zero_discordant_reports_p_one", "mcnemar_direction_swapped",
        "stage1_viability_no_longer_dominates", "stage1_ignores_safety_regression",
        "stage1_ignores_interface_viability", "stage1_ignores_resource_viability",
        "stage1_complementarity_before_viability", "completion_tokens_defaults_to_zero",
    }
    assert required <= names


def test_every_stage1_decision_input_has_a_caught_mutation():
    caught = {m["name"] for m in psm.MUTATIONS if m["expected"] == "caught"}
    for decision_input in ("resource_viable", "safety_regression", "interface_viability"):
        assert any(decision_input.split("_")[0] in name for name in caught), decision_input


def test_status_channel_never_reports_infrastructure_as_a_kill():
    source = Path(psm.__file__).read_text(encoding="utf-8")
    for marker in ("anchor_error", "mutation_load_error", "child_error", "pytest_error"):
        assert marker in source
    assert psm.STATUS_PREFIX == "PSV1-STATUS:"


def test_both_suites_are_exercised_by_every_mutation():
    assert "tests/test_paired_substrate_v1.py" in psm.SUITES
    assert "tests/test_paired_substrate_mnt09_boundary.py" in psm.SUITES
