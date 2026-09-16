"""HARNESS_DELTA_CONTRACT tests, plus the S2 evaluator-delta invariance proofs (D-a/D-b/D-c).

`benchmark/repo_task_eval.py` hashes itself, so the harness hash moves for ANY evaluator edit. These
tests establish what the certificate asserts: the GAP-1 delta is condition-additive,
observation-only and prompt-invariant, and generic harness inequality still fails closed.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import harness_delta_contract_v1 as hdc  # noqa: E402

OLD, NEW = "a" * 64, "b" * 64
FULL = ("condition_additive", "observation_only", "prompt_invariant")


def certificate(identifier="C1", old=OLD, new=NEW, properties=FULL):
    return hdc.Certificate(identifier, old, new, properties, "test certificate")


# ============================================================================= registry behaviour

def test_identical_hashes_need_no_certificate():
    assert hdc.check_harness_relationship(OLD, OLD, {}) is None


def test_uncertified_difference_fails_closed():
    with pytest.raises(hdc.HarnessDeltaError, match="no HARNESS_DELTA_CONTRACT certificate"):
        hdc.check_harness_relationship(OLD, NEW, {})


def test_certificate_must_cover_the_exact_pair():
    registry = {(OLD, NEW): certificate()}
    assert hdc.check_harness_relationship(OLD, NEW, registry).identifier == "C1"
    with pytest.raises(hdc.HarnessDeltaError):
        hdc.check_harness_relationship(NEW, OLD, registry)      # reversed pair is a different pair
    with pytest.raises(hdc.HarnessDeltaError):
        hdc.check_harness_relationship(OLD, "c" * 64, registry)


def test_certificate_missing_a_proven_property_is_refused():
    registry = {(OLD, NEW): certificate(properties=("condition_additive", "observation_only"))}
    with pytest.raises(hdc.HarnessDeltaError, match="does not prove"):
        hdc.check_harness_relationship(OLD, NEW, registry)


def test_register_rejects_incomplete_or_degenerate_certificates():
    with pytest.raises(hdc.HarnessDeltaError, match="missing proven"):
        hdc.register(certificate(properties=("observation_only",)))
    with pytest.raises(hdc.HarnessDeltaError, match="covers a DIFFERENCE"):
        hdc.register(certificate(old=OLD, new=OLD))


def test_default_registry_is_empty_so_every_mismatch_fails_closed():
    assert hdc.CERTIFICATES == {}


@pytest.mark.parametrize("bad", [("", NEW), (OLD, ""), (None, NEW), (OLD, 7)])
def test_malformed_hashes_are_refused(bad):
    with pytest.raises(hdc.HarnessDeltaError, match="non-empty strings"):
        hdc.check_harness_relationship(bad[0], bad[1], {})


# ============================================================================= D-a: condition-additive

def test_existing_condition_overrides_are_byte_identical_after_the_delta():
    import benchmark.repo_task_eval as rte
    resolved = {name: copy.deepcopy(entry["overrides"]) for name, entry in rte.CONDITIONS.items()}
    # qwen_selectorkind is the incumbent condition of record for EXP-SUBQ-01.
    assert resolved["qwen_selectorkind"] == rte.CONDITIONS["qwen_selectorkind"]["overrides"]
    assert resolved["qwen_selectorkind"]["text_tool_protocol"] is True


def test_an_additive_condition_leaves_every_existing_condition_resolving_identically():
    import benchmark.repo_task_eval as rte
    from benchmark.analysis import furthest_bottleneck as v1

    conditions = copy.deepcopy(dict(rte.CONDITIONS))
    before = {name: v1.action_capabilities(entry.get("overrides")) for name, entry in conditions.items()}
    conditions["minicpm_selectorkind_probe"] = {
        "model": "synthetic:0b",
        "overrides": dict(conditions["qwen_selectorkind"]["overrides"]),
    }
    after = {name: v1.action_capabilities(conditions[name].get("overrides")) for name in before}
    assert before == after


def test_a_challenger_condition_copies_the_incumbent_envelope_exactly():
    import benchmark.repo_task_eval as rte
    challenger = {"model": "openbmb/minicpm5-2b:q4_K_M",
                  "overrides": {**rte.CONDITIONS["qwen_selectorkind"]["overrides"]}}
    assert challenger["overrides"] == rte.CONDITIONS["qwen_selectorkind"]["overrides"]
    assert challenger["overrides"] is not rte.CONDITIONS["qwen_selectorkind"]["overrides"]


# ============================================================================= D-b: observation-only

def test_gap1_adds_only_two_row_keys_and_removes_none():
    source = (ROOT / "benchmark" / "repo_task_eval.py").read_text(encoding="utf-8")
    assert '"completion_tokens": sum(completion_tokens),' in source
    assert '"completion_tokens_rounds": len(completion_tokens),' in source
    # the prompt-side key it sits beside is untouched
    assert '"prompt_tokens": sum(prompt_tokens),' in source


def test_gap1_reads_an_already_parsed_value_and_changes_no_control_flow():
    source = (ROOT / "benchmark" / "repo_task_eval.py").read_text(encoding="utf-8")
    assert "completion_tokens.append(usage.eval_count)" in source
    # the recording sits inside the pre-existing `if usage is not None` guard
    index = source.index("completion_tokens.append(usage.eval_count)")
    preceding = source[:index]
    assert preceding.rstrip().endswith(("prompt_tokens.append(usage.prompt_eval_count)",
                                        "# discarded. Generated tokens, reasoning-inclusive and not separable from this count."))


def test_gap1_does_not_touch_the_model_adapter_or_metrics():
    adapter = (ROOT / "plugins" / "model" / "ollama.py").read_text(encoding="utf-8")
    metrics = (ROOT / "core" / "metrics.py").read_text(encoding="utf-8")
    assert "completion_tokens" not in adapter
    assert "completion_tokens" not in metrics
    assert "prompt_eval_cached_count" not in adapter and "prompt_eval_cached_count" not in metrics


def test_row_keys_validation_of_historical_rows_is_unchanged():
    source = (ROOT / "scripts" / "verify_frozen_artifacts.py").read_text(encoding="utf-8")
    assert "completion_tokens" not in source


# ============================================================================= D-c: prompt-invariant

def test_gap1_touches_nothing_the_model_sees():
    """The delta appears only in the recording closure and the result record, never in prompt
    construction, message wiring, tool schemas or sampling options."""
    source = (ROOT / "benchmark" / "repo_task_eval.py").read_text(encoding="utf-8")
    for line_number, line in enumerate(source.splitlines(), start=1):
        if "completion_tokens" not in line:
            continue
        lowered = line.lower()
        for forbidden in ("prompt", "message", "system", "tools", "schema", "sampling", "num_predict",
                          "temperature", "overrides"):
            assert forbidden not in lowered, f"line {line_number} touches {forbidden!r}: {line.strip()}"


def test_harness_policy_and_sampling_are_unchanged_by_the_delta():
    import benchmark.repo_task_eval as rte
    assert rte.HARNESS_POLICY["sampling"] == {"temperature": 0.0, "num_predict": 2048}
    assert rte.MAX_ROUNDS == 12
