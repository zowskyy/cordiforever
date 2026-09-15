"""Fast structural checks for the reproducible taxonomy mutation definitions (the full runner is a manual command)."""

from __future__ import annotations

from benchmark.analysis import furthest_bottleneck_mutations as fbm


def test_every_mutation_anchor_occurs_exactly_once_and_mutant_compiles():
    source = fbm.SOURCE.read_text(encoding="utf-8")
    for mutation in fbm.MUTATIONS:
        mutated = fbm.mutated_source(mutation, source)
        assert mutated != source, mutation["name"]
        compile(mutated, str(fbm.SOURCE), "exec")


def test_mutation_definitions_are_well_formed():
    names = [m["name"] for m in fbm.MUTATIONS]
    assert len(names) == len(set(names))
    caught = {m["name"] for m in fbm.MUTATIONS if m["expected"] == "caught"}
    for mutation in fbm.MUTATIONS:
        assert mutation["expected"] in ("caught", "equivalent")
        if mutation["expected"] == "equivalent":
            assert mutation.get("proven_by") in caught and mutation.get("reason")


def test_required_protections_are_present():
    names = {m["name"] for m in fbm.MUTATIONS}
    required = {"d0_harness_uses_contract_as_label", "exact_reference_patch_required", "unknown_structural_necessity_as_false",
                "reference_added_intent_ignored", "d0_contract_changes_label", "harness_insertion_marked_unsupported",
                "stage_order_swapped", "f0_without_blocking_condition", "wrong_target_counted_as_f6", "f7_without_positive_evidence",
                "unknown_correctness_counted_as_f6", "guard_judgement_changes_label", "undetermined_collapsed_into_f8",
                "json_prefix_only_relevance", "d11_skips_non_edit_mutations", "f6_subtype_forced_single"}
    assert required <= names


def test_namespace_package_loader_registers_parent_attribute():
    import sys

    import benchmark.analysis
    import benchmark.analysis.furthest_bottleneck as original

    try:
        module = fbm.load_mutated_module(next(m for m in fbm.MUTATIONS if m["name"] == "f6_subtype_forced_single"))
        assert module is not original
        assert sys.modules[fbm.MODULE] is module and benchmark.analysis.furthest_bottleneck is module
    finally:
        sys.modules[fbm.MODULE] = original
        benchmark.analysis.furthest_bottleneck = original
    assert sys.modules[fbm.MODULE] is original and benchmark.analysis.furthest_bottleneck is original
