"""MNT-09 tests: applicability admission, historical equivalence, firewalls and additivity.

Synthetic fixtures except where historical reproduction is explicitly under test. No model is
contacted, no scorer is run, no frozen artifact is written.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import taxonomy_population_registry_v1 as reg  # noqa: E402

RESULTS = ROOT / "benchmark" / "results" / "repo_task_eval.jsonl"


# ============================================================================= fixtures

def _results_rows() -> list[tuple[int, dict]]:
    rows: list[tuple[int, dict]] = []
    for number, line in enumerate(RESULTS.read_bytes().decode("utf-8").splitlines(), start=1):
        if line.strip():
            rows.append((number, json.loads(line)))
    return rows


@pytest.fixture(scope="module")
def results_rows() -> list[tuple[int, dict]]:
    return _results_rows()


@pytest.fixture()
def conditions() -> dict:
    import benchmark.repo_task_eval as rte
    return copy.deepcopy(dict(rte.CONDITIONS))


SYNTH_TASKS = ["synth_alpha", "synth_beta"]
SYNTH_GATE = "a" * 64


def synthetic_record(**overrides) -> dict:
    record = {
        "population_id": "SYNTH_FUTURE",
        "methodology": dict(reg.FROZEN_METHODOLOGY),
        "new_data_application": True,
        "arms": [{"arm_id": "synth_arm", "role": "primary", "condition": "synthetic_probe",
                  "gate_sha256": SYNTH_GATE, "split": "dev"}],
        "task_set": list(SYNTH_TASKS),
        "expected_rows_per_arm": 2,
        "expected_total_rows": 2,
        "input_contract_version": reg.INPUT_CONTRACT_V1,
        "registration_ref": {"gate_sha256": SYNTH_GATE, "commit": "0" * 40},
    }
    record.update(overrides)
    return record


def synthetic_row(task: str, *, split="dev", condition="synthetic_probe", gate=SYNTH_GATE,
                  model="synthetic:0b", **overrides) -> dict:
    row = {
        "task": task,
        "split": split,
        "condition": condition,
        "model": model,
        "model_digest": "d" * 64,
        "calls": [{"tool": "read_file", "round": 1, "args": {"path": "a.py"}, "success": True}],
        "fingerprint": f"fp_{task}",
        "experiment": {"gate": {"sha256": gate}},
        "expected_outcome": "verified_done",
        "oracle_passed": False,
    }
    row.update(overrides)
    return row


def synthetic_rows(**overrides) -> list[tuple[int, dict]]:
    return [(index, synthetic_row(task, **overrides)) for index, task in enumerate(SYNTH_TASKS, start=1)]


@pytest.fixture()
def synth_conditions(conditions) -> dict:
    conditions["synthetic_probe"] = {
        "model": "synthetic:0b",
        "overrides": dict(conditions["qwen_selectorkind"]["overrides"]),
    }
    return conditions


# ============================================================================= test 1 - selection identity

def test_1_historical_population_selects_exactly_the_runner_selection(results_rows, conditions):
    """Level A: admitted historical population == the frozen runner's select_arms selection."""
    from benchmark.analysis import run_furthest_bottleneck_classification_v2 as runner

    lines = RESULTS.read_bytes().decode("utf-8").splitlines()
    runner_selection = runner.select_arms(lines)

    admission = reg.admit_population(reg.historical_population(), results_rows, conditions)

    assert set(admission.selection) == set(runner_selection)
    for arm_id, runner_rows in runner_selection.items():
        mine = admission.selection[arm_id]
        assert [number for number, _ in mine] == [number for number, _ in runner_rows]
        assert [row["task"] for _, row in mine] == [row["task"] for _, row in runner_rows]
        assert [row["fingerprint"] for _, row in mine] == [row["fingerprint"] for _, row in runner_rows]


def test_1b_historical_observed_counts_match_frozen_facts(results_rows, conditions):
    admission = reg.admit_population(reg.historical_population(), results_rows, conditions)
    assert admission.total_rows == 120
    assert admission.observed_solvable == 96
    assert admission.observed_unsuccessful_solvable == 78
    assert all(obs.unsuccessful_solvable == 13 for obs in admission.arms)
    assert len(admission.arms) == 6


# ============================================================================= test 2 - registered future arm

def test_2_explicitly_registered_synthetic_future_arm_is_accepted(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    admission = reg.admit_population(prr, synthetic_rows(), synth_conditions)
    assert admission.population_id == "SYNTH_FUTURE"
    assert admission.total_rows == 2
    assert admission.observed_solvable == 2
    assert admission.observed_unsuccessful_solvable == 2


# ============================================================================= test 3 - unregistered arm

def test_3_unregistered_arm_rows_are_never_selected(synth_conditions):
    """A9: rows from an arm the PRR does not declare are invisible, and the count check then fails."""
    prr = reg.load_prr(synthetic_record())
    rows = synthetic_rows() + [(99, synthetic_row("synth_gamma", gate="b" * 64))]
    admission = reg.admit_population(prr, rows, synth_conditions)
    assert [row["task"] for _, row in admission.selection["synth_arm"]] == SYNTH_TASKS


def test_3b_unregistered_arm_cannot_satisfy_the_population(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    unregistered_only = [(index, synthetic_row(task, gate="b" * 64))
                         for index, task in enumerate(SYNTH_TASKS, start=1)]
    with pytest.raises(reg.Stop, match="A7"):
        reg.admit_population(prr, unregistered_only, synth_conditions)


def test_3c_unregistered_condition_is_not_selected(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    rows = [(index, synthetic_row(task, condition="qwen_selectorkind"))
            for index, task in enumerate(SYNTH_TASKS, start=1)]
    with pytest.raises(reg.Stop, match="A7"):
        reg.admit_population(prr, rows, synth_conditions)


# ============================================================================= test 4 - heldout firewall

def test_4_heldout_split_is_rejected_unconditionally(synth_conditions):
    prr = reg.load_prr(synthetic_record(
        arms=[{"arm_id": "synth_arm", "role": "primary", "condition": "synthetic_probe",
               "gate_sha256": SYNTH_GATE, "split": "heldout"}]))
    with pytest.raises(reg.Stop, match="A5"):
        reg.admit_population(prr, synthetic_rows(split="heldout"), synth_conditions)


def test_4b_heldout_rows_are_never_selected_by_a_dev_population(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    rows = synthetic_rows() + [(50, synthetic_row("synth_alpha", split="heldout"))]
    admission = reg.admit_population(prr, rows, synth_conditions)
    assert all(row["split"] == "dev" for _, row in admission.selection["synth_arm"])


def test_4c_permitted_splits_contains_only_dev():
    assert reg.PERMITTED_SPLITS == frozenset({"dev"})


def test_4d_no_prr_field_flag_or_option_can_widen_permitted_splits(synth_conditions):
    """A5 must be unconditional: no record field enables heldout."""
    for attempt in ({"split": "heldout"}, {"split": "HELDOUT"}, {"split": "dev,heldout"}):
        prr_record = synthetic_record(
            arms=[{"arm_id": "synth_arm", "role": "primary", "condition": "synthetic_probe",
                   "gate_sha256": SYNTH_GATE, **attempt}])
        prr = reg.load_prr(prr_record)
        with pytest.raises(reg.Stop, match="A5"):
            reg.admit_population(prr, synthetic_rows(), synth_conditions)
    # an unknown field that might try to carry an override is refused at load time
    with pytest.raises(reg.Stop, match="unknown field"):
        reg.load_prr(synthetic_record(permit_heldout=True))


def test_4e_permitted_splits_is_never_widened_at_runtime():
    """Structural corroboration; the behavioural proof is test_4/4b/4c/4d.

    PERMITTED_SPLITS is read in exactly one place and is never rebound, extended or unioned, so no
    code path can widen it. A literal text scan for 'heldout' would be meaningless here (the word
    legitimately appears in the prohibition's own documentation), so the check is on mutation of the
    constant instead.
    """
    source = (ROOT / "benchmark" / "analysis" / "taxonomy_population_registry_v1.py").read_text(encoding="utf-8")
    bindings = re.findall(r"^PERMITTED_SPLITS\s*(?::[^=]+)?=", source, re.M)
    assert len(bindings) == 1, "PERMITTED_SPLITS must be bound exactly once, at module level"
    for forbidden in ("PERMITTED_SPLITS |", "PERMITTED_SPLITS.union", "PERMITTED_SPLITS.add",
                      "PERMITTED_SPLITS +", "PERMITTED_SPLITS.update"):
        assert forbidden not in source, f"PERMITTED_SPLITS must not be mutated: {forbidden!r}"
    assert isinstance(reg.PERMITTED_SPLITS, frozenset)


def test_4f_malformed_heldout_row_in_a_declared_family_still_cannot_be_admitted(synth_conditions):
    """A heldout row can never reach the row contract, because its family is never declared."""
    prr = reg.load_prr(synthetic_record())
    rows = synthetic_rows() + [(51, synthetic_row("synth_alpha", split="heldout", experiment={}))]
    admission = reg.admit_population(prr, rows, synth_conditions)
    assert admission.total_rows == 2


# ============================================================================= test 5 - malformed input

@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r.pop("population_id"), "missing field"),
    (lambda r: r.update(population_id=""), "non-empty string"),
    (lambda r: r.update(methodology={}), "non-empty mapping"),
    (lambda r: r.update(new_data_application=1), "literally True or False"),
    (lambda r: r.update(new_data_application="yes"), "literally True or False"),
    (lambda r: r.update(arms=[]), "non-empty sequence"),
    (lambda r: r.update(task_set=[]), "non-empty sequence"),
    (lambda r: r.update(task_set=["a", "a"]), "duplicate task"),
    (lambda r: r.update(expected_total_rows=7), "expected_total_rows must equal"),
    (lambda r: r.update(expected_rows_per_arm=True), "positive int"),
    (lambda r: r.update(input_contract_version="v0"), "unsupported input_contract_version"),
    (lambda r: r.update(task_set=["a", "b", "c"], expected_rows_per_arm=2, expected_total_rows=2),
     "expected_rows_per_arm must equal the declared task_set size"),
    (lambda r: r.update(registration_ref={}), "non-empty string"),
    (lambda r: r.update(extra_field=1), "unknown field"),
    (lambda r: r.update(arms=[
        {"arm_id": "one", "role": "primary", "condition": "synthetic_probe",
         "gate_sha256": SYNTH_GATE, "split": "dev"},
        {"arm_id": "two", "role": "identity", "condition": "synthetic_probe",
         "gate_sha256": SYNTH_GATE, "split": "dev"}],
        expected_total_rows=4),
     "share a (split, condition, gate_sha256) selection triple"),
    (lambda r: r.update(arms=[
        {"arm_id": "same", "role": "primary", "condition": "synthetic_probe",
         "gate_sha256": SYNTH_GATE, "split": "dev"},
        {"arm_id": "same", "role": "identity", "condition": "other",
         "gate_sha256": SYNTH_GATE, "split": "dev"}],
        expected_total_rows=4),
     "duplicate arm_id"),
])
def test_5_malformed_prr_is_rejected(mutate, expected):
    record = synthetic_record()
    mutate(record)
    with pytest.raises(reg.Stop, match=re.escape(expected)):
        reg.load_prr(record)


def test_5b_methodology_hash_mismatch_is_rejected(synth_conditions):
    bad = dict(reg.FROZEN_METHODOLOGY)
    bad["benchmark/analysis/furthest_bottleneck_v2.py"] = "0" * 64
    prr = reg.load_prr(synthetic_record(methodology=bad))
    with pytest.raises(reg.Stop, match="A2"):
        reg.admit_population(prr, synthetic_rows(), synth_conditions)


def test_5b2_on_disk_methodology_drift_is_rejected(synth_conditions, monkeypatch):
    """A2 must verify the artifact on disk, not merely that the PRR quotes the right constant.

    Frozen artifacts must never be modified, so the disk read is redirected instead: if the file ever
    drifted from its frozen hash, admission must stop.
    """
    drifted = "benchmark/analysis/furthest_bottleneck_v2.py"
    monkeypatch.setattr(reg, "_sha256_file",
                        lambda rel: "9" * 64 if rel == drifted else reg.FROZEN_METHODOLOGY[rel])
    prr = reg.load_prr(synthetic_record())
    with pytest.raises(reg.Stop, match="on disk"):
        reg.admit_population(prr, synthetic_rows(), synth_conditions)


def test_5c_incomplete_methodology_set_is_rejected(synth_conditions):
    partial = dict(reg.FROZEN_METHODOLOGY)
    partial.pop("benchmark/analysis/furthest_bottleneck.py")
    prr = reg.load_prr(synthetic_record(methodology=partial))
    with pytest.raises(reg.Stop, match="A2"):
        reg.admit_population(prr, synthetic_rows(), synth_conditions)


def test_5d_unresolvable_condition_is_rejected(conditions):
    prr = reg.load_prr(synthetic_record())
    with pytest.raises(reg.Stop, match="A4"):
        reg.admit_population(prr, synthetic_rows(), conditions)


def test_5e_condition_without_overrides_is_rejected(conditions):
    conditions["synthetic_probe"] = {"model": "synthetic:0b"}
    prr = reg.load_prr(synthetic_record())
    with pytest.raises(reg.Stop, match="A4"):
        reg.admit_population(prr, synthetic_rows(), conditions)


@pytest.mark.parametrize("mutate,expected", [
    (lambda row: row.pop("calls"), "missing key"),
    (lambda row: row.update(calls="not-a-list"), "calls must be a list"),
    (lambda row: row.update(calls=[["not", "a", "mapping"]]), "every call must be a mapping"),
    (lambda row: row.update(fingerprint=""), "fingerprint must be a non-empty string"),
    (lambda row: row.pop("experiment"), "missing key"),
    (lambda row: row.update(experiment={}), "experiment.gate must be a mapping"),
])
def test_5f_malformed_row_is_rejected(mutate, expected, synth_conditions):
    prr = reg.load_prr(synthetic_record())
    rows = synthetic_rows()
    mutate(rows[0][1])
    with pytest.raises(reg.Stop, match=re.escape(expected)):
        reg.admit_population(prr, rows, synth_conditions)


def test_5g_duplicate_task_within_an_arm_is_rejected(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    rows = [(1, synthetic_row("synth_alpha")), (2, synthetic_row("synth_alpha"))]
    with pytest.raises(reg.Stop, match="A8"):
        reg.admit_population(prr, rows, synth_conditions)


def test_5h_task_set_mismatch_is_rejected(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    rows = [(1, synthetic_row("synth_alpha")), (2, synthetic_row("synth_delta"))]
    with pytest.raises(reg.Stop, match="A8"):
        reg.admit_population(prr, rows, synth_conditions)


# ============================================================================= structure vs outcome (PRR correction)

@pytest.mark.parametrize("field_name", ["solvable", "unsuccessful_solvable", "unsuccessful_per_arm",
                                        "historical_assertions", "label_counts"])
def test_future_prr_may_not_preregister_outcome_dependent_quantities(field_name):
    """A11 must fire for this specific reason, not incidentally as an unknown field."""
    payload = {"solvable": 2} if field_name == "historical_assertions" else 2
    with pytest.raises(reg.Stop, match="A11") as excinfo:
        reg.load_prr(synthetic_record(**{field_name: payload}))
    assert field_name in str(excinfo.value)


def test_historical_prr_may_carry_historical_assertions():
    prr = reg.historical_population()
    assert prr.is_historical
    assert prr.historical_assertions == {"solvable": 96, "unsuccessful_solvable": 78,
                                         "unsuccessful_per_arm": 13}


def test_future_admission_reports_observed_counts_without_preregistration(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    assert prr.historical_assertions is None
    rows = synthetic_rows()
    rows[0][1]["oracle_passed"] = True
    admission = reg.admit_population(prr, rows, synth_conditions)
    assert admission.observed_solvable == 2
    assert admission.observed_unsuccessful_solvable == 1


def test_historical_assertion_violation_is_rejected(results_rows, conditions):
    record = copy.deepcopy(reg.HISTORICAL_MNT07_DEV_RECORD)
    record["historical_assertions"]["unsuccessful_solvable"] = 77
    with pytest.raises(reg.Stop, match="historical reproduction"):
        reg.admit_population(reg.load_prr(record), results_rows, conditions)


# ============================================================================= test 7 - model agnosticism

def test_7_admission_is_identical_under_different_model_identity(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    a = reg.admit_population(prr, synthetic_rows(model="alpha:1b"), synth_conditions)
    b = reg.admit_population(prr, synthetic_rows(model="omega:99b"), synth_conditions)
    assert (a.total_rows, a.observed_solvable, a.observed_unsuccessful_solvable) == \
           (b.total_rows, b.observed_solvable, b.observed_unsuccessful_solvable)
    assert [row["task"] for _, row in a.selection["synth_arm"]] == \
           [row["task"] for _, row in b.selection["synth_arm"]]


def test_7b_admission_never_reads_a_model_field(synth_conditions):
    """A10: rows without any model key at all are admitted unchanged."""
    prr = reg.load_prr(synthetic_record())
    rows = synthetic_rows()
    for _, row in rows:
        for key in reg.PROVENANCE_ONLY_ROW_KEYS:
            row.pop(key, None)
    admission = reg.admit_population(prr, rows, synth_conditions)
    assert admission.total_rows == 2


def test_7c_no_model_keyed_branch_in_admission_source():
    source = (ROOT / "benchmark" / "analysis" / "taxonomy_population_registry_v1.py").read_text(encoding="utf-8")
    body = source.split("# ============================================================================= admission")[1]
    body = body.split("# ============================================================================= historical PRR")[0]
    assert 'row.get("model' not in body
    assert 'row["model' not in body


# ============================================================================= test 8 - purity

def test_8_admission_does_not_mutate_frozen_evidence_or_outputs(results_rows, conditions):
    import hashlib

    watched = [RESULTS]
    for tree in (ROOT / "benchmark" / "analysis" / "output", ROOT / "benchmark" / "analysis" / "output_v2"):
        if tree.is_dir():
            watched.extend(sorted(p for p in tree.rglob("*") if p.is_file()))
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}

    reg.admit_population(reg.historical_population(), results_rows, conditions)

    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    assert before == after


def test_8b_module_opens_no_file_for_writing():
    source = (ROOT / "benchmark" / "analysis" / "taxonomy_population_registry_v1.py").read_text(encoding="utf-8")
    for forbidden in ("write_text", "write_bytes", "open(", "mkdir", "os.replace", "shutil"):
        assert forbidden not in source, f"admission module must stay pure: found {forbidden!r}"


def test_8c_admission_does_not_mutate_input_rows(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    rows = synthetic_rows()
    snapshot = copy.deepcopy(rows)
    reg.admit_population(prr, rows, synth_conditions)
    assert rows == snapshot


# ============================================================================= condition additivity

def test_additivity_existing_conditions_resolve_identically(conditions):
    """N6 regression property: an additive condition cannot change an existing one."""
    from benchmark.analysis import furthest_bottleneck as v1

    before = {name: v1.action_capabilities(entry.get("overrides"))
              for name, entry in conditions.items()}
    snapshot = copy.deepcopy(conditions)

    conditions["synthetic_probe"] = {
        "model": "synthetic:0b",
        "overrides": dict(conditions["qwen_selectorkind"]["overrides"]),
    }
    conditions["synthetic_probe_two"] = {
        "model": "synthetic:1b",
        "overrides": dict(conditions["qwen_astnoop"]["overrides"]),
    }

    after = {name: v1.action_capabilities(conditions[name].get("overrides")) for name in before}
    assert before == after
    assert all(snapshot[name]["overrides"] == conditions[name]["overrides"] for name in before)


def test_additivity_synthetic_condition_resolves_like_its_source(conditions):
    from benchmark.analysis import furthest_bottleneck as v1

    conditions["synthetic_probe"] = {
        "model": "synthetic:0b",
        "overrides": dict(conditions["qwen_selectorkind"]["overrides"]),
    }
    assert v1.action_capabilities(conditions["synthetic_probe"]["overrides"]) == \
           v1.action_capabilities(conditions["qwen_selectorkind"]["overrides"])


def test_additivity_synthetic_condition_needs_an_explicit_prr(conditions, results_rows):
    """A synthetic condition existing in CONDITIONS grants no applicability by itself."""
    conditions["synthetic_probe"] = {
        "model": "synthetic:0b",
        "overrides": dict(conditions["qwen_selectorkind"]["overrides"]),
    }
    admission = reg.admit_population(reg.historical_population(), results_rows, conditions)
    assert "synthetic_probe" not in {arm.arm_id for arm in admission.arms}
    assert admission.total_rows == 120


# ============================================================================= properties

def test_admission_is_order_independent(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    forward = reg.admit_population(prr, synthetic_rows(), synth_conditions)
    reversed_rows = list(reversed(synthetic_rows()))
    backward = reg.admit_population(prr, reversed_rows, synth_conditions)
    assert forward.total_rows == backward.total_rows
    assert {row["task"] for _, row in forward.selection["synth_arm"]} == \
           {row["task"] for _, row in backward.selection["synth_arm"]}


def test_admission_is_idempotent(results_rows, conditions):
    first = reg.admit_population(reg.historical_population(), results_rows, conditions)
    second = reg.admit_population(reg.historical_population(), results_rows, conditions)
    assert first.total_rows == second.total_rows
    assert first.observed_solvable == second.observed_solvable
    assert {a.arm_id: [n for n, _ in a.rows] for a in first.arms} == \
           {a.arm_id: [n for n, _ in a.rows] for a in second.arms}


def test_rejection_names_the_offending_arm_and_rule(synth_conditions):
    prr = reg.load_prr(synthetic_record())
    with pytest.raises(reg.Stop) as excinfo:
        reg.admit_population(prr, synthetic_rows()[:1], synth_conditions)
    message = str(excinfo.value)
    assert "A7" in message and "synth_arm" in message


def test_frozen_methodology_names_exactly_ten_artifacts():
    assert len(reg.FROZEN_METHODOLOGY) == 10


def test_frozen_methodology_hashes_match_disk():
    import hashlib
    for rel, expected in reg.FROZEN_METHODOLOGY.items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == expected, f"{rel} changed: {actual} != {expected}"
