"""Taxonomy population applicability registry (MNT-09, v1).

Authorizes application of the frozen MNT-07/MNT-08 taxonomy to explicitly registered populations.
Specification: benchmark/analysis/taxonomy_population_applicability_v1.md

This module is an applicability/scope extension, not a classifier revision. It changes no stage
definition, no D-fact, no precedence and no frozen artifact. It is pure and read-only: it opens no
file for writing, contacts no model, runs no oracle and executes no scorer.

Fail-closed. Absence of registration is refusal; ambiguity is refusal; a malformed record is refusal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]

#: The immutable MNT-07/MNT-08 artifacts, referenced by exact path and sha256 (Option 4-A).
#: MNT-09 never edits, appends to or re-freezes any of these.
FROZEN_METHODOLOGY: dict[str, str] = {
    "benchmark/analysis/furthest_bottleneck_taxonomy.md":
        "cf5b8764fd15088a95c729d1a8388f8dc95adff07128d62d552a46062f354ce5",
    "benchmark/analysis/furthest_bottleneck.py":
        "6817e1a73454aecfbd81c161a96b0218561a362aad3da10985c7ddcd1f5aff1b",
    "benchmark/analysis/furthest_bottleneck_mutations.py":
        "8352890c0ede42ddf4140dc665463e5ba12b0a840f37b4a19856b5686f18685a",
    "tests/test_furthest_bottleneck.py":
        "055873e8909ef2b0ec6393ad0f327ddcc17567441406299422e04bb9ad825451",
    "tests/test_furthest_bottleneck_mutations.py":
        "658e4aa9608ce845b6c0e5b4b8fe3ee6b750da6234dad6d62a3660b195324615",
    "benchmark/analysis/furthest_bottleneck_taxonomy_v2.md":
        "4af9a3a414c3bf9ddad3a6f63190e4499f97387277349df9908a414a5e68abb2",
    "benchmark/analysis/furthest_bottleneck_v2.py":
        "e713ff4e99b967d3170ae8a41c9fc14eb706ae17065150424df0c085a923adef",
    "benchmark/analysis/furthest_bottleneck_v2_mutations.py":
        "4445c8e8d45e63008320da810ee3fe96bd9787afd09439af6b552bd67762b403",
    "tests/test_furthest_bottleneck_v2.py":
        "f2b897bb5a2dc16c61f0e582e7a2dc0b5dee2d6c5df4496a1c89534ff01f4725",
    "tests/test_producer_call_round_contract.py":
        "81c017bd162ada6c91f067cf28a9efa6e9c7a73e239bdc33c9e0737528af4205",
}

#: A5 heldout firewall. Only "dev" is applicable under MNT-09. Future heldout applicability
#: requires a separate methodology decision that names it explicitly; there is deliberately no
#: field, flag, environment variable or alternate path that can widen this set at runtime.
PERMITTED_SPLITS: frozenset[str] = frozenset({"dev"})

#: A10. Recorded as provenance by the evaluator; never consulted by admission or classification.
PROVENANCE_ONLY_ROW_KEYS: tuple[str, ...] = ("model", "model_digest")

#: A11. Outcome- or taxonomy-derived quantities. Knowable only after a model arm has run and been
#: classified, so a future PRR must not declare them.
OUTCOME_DEPENDENT_FIELDS: tuple[str, ...] = (
    "solvable", "unsuccessful_solvable", "unsuccessful_per_arm", "historical_assertions",
    "labels", "label_counts", "bottleneck_shares", "oracle_passed", "d3_evidence",
)

#: A6 row contract.
REQUIRED_ROW_KEYS: tuple[str, ...] = ("task", "split", "condition", "calls", "fingerprint", "experiment")

INPUT_CONTRACT_V1 = "repo_task_eval_row_v1"

_REQUIRED_PRR_FIELDS: tuple[str, ...] = (
    "population_id", "methodology", "new_data_application", "arms", "task_set",
    "expected_rows_per_arm", "expected_total_rows", "input_contract_version", "registration_ref",
)
_OPTIONAL_PRR_FIELDS: tuple[str, ...] = ("historical_assertions",)
_REQUIRED_ARM_FIELDS: tuple[str, ...] = ("arm_id", "role", "condition", "gate_sha256", "split")


class Stop(Exception):
    """A population outside MNT-09's authorized applicability, or a failed admission rule."""


@dataclass(frozen=True)
class Arm:
    arm_id: str
    role: str
    condition: str
    gate_sha256: str
    split: str


@dataclass(frozen=True)
class PopulationRegistration:
    """Preregistered structure only. Outcome-dependent quantities are deliberately absent."""

    population_id: str
    methodology: Mapping[str, str]
    new_data_application: bool
    arms: tuple[Arm, ...]
    task_set: frozenset[str]
    expected_rows_per_arm: int
    expected_total_rows: int
    input_contract_version: str
    registration_ref: Mapping[str, str]
    historical_assertions: Mapping[str, int] | None = None

    @property
    def is_historical(self) -> bool:
        return self.new_data_application is not True


@dataclass(frozen=True)
class ArmObservation:
    """Observed facts, computed after admission. Never preregistered for a future population."""

    arm_id: str
    rows: tuple[tuple[int, Mapping[str, Any]], ...]
    solvable: int
    unsuccessful_solvable: int


@dataclass(frozen=True)
class Admission:
    population_id: str
    arms: tuple[ArmObservation, ...]
    total_rows: int
    observed_solvable: int
    observed_unsuccessful_solvable: int
    selection: Mapping[str, tuple[tuple[int, Mapping[str, Any]], ...]] = field(default_factory=dict)


# ============================================================================= helpers

def _sha256_file(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Stop(message)


def _str_field(obj: Mapping[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    _require(isinstance(value, str) and value != "", f"{where}: {key} must be a non-empty string")
    return value  # type: ignore[return-value]


def _int_field(obj: Mapping[str, Any], key: str, where: str) -> int:
    value = obj.get(key)
    # bool is a subclass of int and is never a valid count here.
    _require(type(value) is int and value > 0, f"{where}: {key} must be a positive int")
    return value  # type: ignore[return-value]


# ============================================================================= A1, A3, A11 - loading

def load_prr(obj: Any) -> PopulationRegistration:
    """A1/A3/A11. Parse and validate a Population Registration Record's structure."""
    _require(isinstance(obj, Mapping), "PRR: record must be a mapping")

    # A11 is checked before the generic unknown-field rule so that preregistering an outcome-dependent
    # quantity is refused for that specific reason, rather than incidentally as an unknown field.
    if obj.get("new_data_application") is True:
        declared_outcomes = sorted(set(obj) & set(OUTCOME_DEPENDENT_FIELDS))
        _require(not declared_outcomes,
                 f"A11: outcome-dependent field(s) {declared_outcomes} may not be preregistered "
                 f"for new-data application")

    unknown = sorted(set(obj) - set(_REQUIRED_PRR_FIELDS) - set(_OPTIONAL_PRR_FIELDS))
    _require(not unknown, f"PRR: unknown field(s) {unknown}")
    missing = [key for key in _REQUIRED_PRR_FIELDS if key not in obj]
    _require(not missing, f"PRR: missing field(s) {missing}")

    population_id = _str_field(obj, "population_id", "PRR")

    methodology = obj.get("methodology")
    _require(isinstance(methodology, Mapping) and methodology, "PRR: methodology must be a non-empty mapping")
    _require(all(isinstance(k, str) and isinstance(v, str) for k, v in methodology.items()),
             "PRR: methodology entries must be path -> sha256 strings")

    # A3: identity, never truthiness. 1, "yes" and other truthy values are rejected.
    new_data_application = obj.get("new_data_application")
    _require(new_data_application is True or new_data_application is False,
             "PRR: new_data_application must be literally True or False")

    raw_arms = obj.get("arms")
    _require(isinstance(raw_arms, Sequence) and not isinstance(raw_arms, (str, bytes)) and len(raw_arms) > 0,
             "PRR: arms must be a non-empty sequence")
    arms: list[Arm] = []
    for index, raw in enumerate(raw_arms):
        where = f"PRR: arms[{index}]"
        _require(isinstance(raw, Mapping), f"{where} must be a mapping")
        arm_unknown = sorted(set(raw) - set(_REQUIRED_ARM_FIELDS))
        _require(not arm_unknown, f"{where}: unknown field(s) {arm_unknown}")
        arms.append(Arm(
            arm_id=_str_field(raw, "arm_id", where),
            role=_str_field(raw, "role", where),
            condition=_str_field(raw, "condition", where),
            gate_sha256=_str_field(raw, "gate_sha256", where),
            split=_str_field(raw, "split", where),
        ))
    arm_ids = [arm.arm_id for arm in arms]
    _require(len(set(arm_ids)) == len(arm_ids), "PRR: duplicate arm_id")
    # Two arms sharing a selection triple would silently admit the same rows twice under different
    # labels, so the triple must identify an arm uniquely.
    triples = [(arm.split, arm.condition, arm.gate_sha256) for arm in arms]
    _require(len(set(triples)) == len(triples),
             "PRR: two arms share a (split, condition, gate_sha256) selection triple")

    raw_tasks = obj.get("task_set")
    _require(isinstance(raw_tasks, Sequence) and not isinstance(raw_tasks, (str, bytes)) and len(raw_tasks) > 0,
             "PRR: task_set must be a non-empty sequence")
    _require(all(isinstance(t, str) and t for t in raw_tasks), "PRR: task_set entries must be non-empty strings")
    _require(len(set(raw_tasks)) == len(raw_tasks), "PRR: duplicate task in task_set")
    task_set = frozenset(raw_tasks)

    expected_rows_per_arm = _int_field(obj, "expected_rows_per_arm", "PRR")
    expected_total_rows = _int_field(obj, "expected_total_rows", "PRR")
    _require(expected_total_rows == expected_rows_per_arm * len(arms),
             "PRR: expected_total_rows must equal expected_rows_per_arm * len(arms)")
    _require(expected_rows_per_arm == len(task_set),
             "PRR: expected_rows_per_arm must equal the declared task_set size")

    input_contract_version = _str_field(obj, "input_contract_version", "PRR")
    _require(input_contract_version == INPUT_CONTRACT_V1,
             f"PRR: unsupported input_contract_version {input_contract_version!r}")

    registration_ref = obj.get("registration_ref")
    _require(isinstance(registration_ref, Mapping), "PRR: registration_ref must be a mapping")
    for key in ("gate_sha256", "commit"):
        _str_field(registration_ref, key, "PRR: registration_ref")

    historical_assertions = obj.get("historical_assertions")
    if historical_assertions is not None:
        _require(new_data_application is False,
                 "PRR: historical_assertions is permitted only for a historical population")
        _require(isinstance(historical_assertions, Mapping), "PRR: historical_assertions must be a mapping")
        _require(all(type(v) is int for v in historical_assertions.values()),
                 "PRR: historical_assertions values must be ints")

    return PopulationRegistration(
        population_id=population_id,
        methodology=dict(methodology),
        new_data_application=new_data_application,
        arms=tuple(arms),
        task_set=task_set,
        expected_rows_per_arm=expected_rows_per_arm,
        expected_total_rows=expected_total_rows,
        input_contract_version=input_contract_version,
        registration_ref=dict(registration_ref),
        historical_assertions=dict(historical_assertions) if historical_assertions is not None else None,
    )


# ============================================================================= A2, A4, A5 - preflight

def check_methodology(prr: PopulationRegistration) -> None:
    """A2. Every frozen artifact must match, exactly and completely."""
    declared, frozen = dict(prr.methodology), FROZEN_METHODOLOGY
    _require(set(declared) == set(frozen),
             f"A2: methodology must name exactly the frozen artifact set; "
             f"missing {sorted(set(frozen) - set(declared))}, unexpected {sorted(set(declared) - set(frozen))}")
    for rel, expected in frozen.items():
        _require(declared[rel] == expected, f"A2: {rel} declared {declared[rel]} != frozen {expected}")
        actual = _sha256_file(rel)
        _require(actual == expected, f"A2: {rel} on disk {actual} != frozen {expected}")


def check_authorization(prr: PopulationRegistration) -> None:
    """A3. Non-historical application must be explicitly authorized."""
    if not prr.is_historical:
        _require(prr.new_data_application is True,
                 "A3: new_data_application must satisfy `is True` for a non-historical population")


def check_conditions(prr: PopulationRegistration, conditions: Mapping[str, Any]) -> None:
    """A4. Every registered condition must resolve to an overrides mapping."""
    for arm in prr.arms:
        entry = conditions.get(arm.condition)
        _require(isinstance(entry, Mapping),
                 f"A4: {arm.arm_id}: condition {arm.condition!r} is not defined in CONDITIONS")
        _require(isinstance(entry.get("overrides"), Mapping),
                 f"A4: {arm.arm_id}: condition {arm.condition!r} has no overrides mapping")


def check_splits(prr: PopulationRegistration) -> None:
    """A5. Heldout is rejected unconditionally."""
    for arm in prr.arms:
        _require(arm.split in PERMITTED_SPLITS,
                 f"A5: {arm.arm_id}: split {arm.split!r} is not applicable under MNT-09 "
                 f"(permitted: {sorted(PERMITTED_SPLITS)})")


# ============================================================================= A6 - row contract

def check_row_contract(arm_id: str, number: int, row: Mapping[str, Any]) -> None:
    """A6. The frozen taxonomy's required input shape."""
    where = f"A6: {arm_id}/line {number}"
    missing = [key for key in REQUIRED_ROW_KEYS if key not in row]
    _require(not missing, f"{where}: missing key(s) {missing}")
    _require(isinstance(row.get("task"), str) and row["task"], f"{where}: task must be a non-empty string")
    calls = row.get("calls")
    _require(isinstance(calls, list), f"{where}: calls must be a list")
    _require(all(isinstance(call, Mapping) for call in calls), f"{where}: every call must be a mapping")
    _require(isinstance(row.get("fingerprint"), str) and row["fingerprint"],
             f"{where}: fingerprint must be a non-empty string")
    experiment = row.get("experiment")
    _require(isinstance(experiment, Mapping), f"{where}: experiment must be a mapping")
    gate = experiment.get("gate")
    _require(isinstance(gate, Mapping), f"{where}: experiment.gate must be a mapping")
    _require(isinstance(gate.get("sha256"), str) and gate["sha256"],
             f"{where}: experiment.gate.sha256 must be a non-empty string")


# ============================================================================= admission

def _row_gate(row: Mapping[str, Any]) -> Any:
    experiment = row.get("experiment")
    if not isinstance(experiment, Mapping):
        return None
    gate = experiment.get("gate")
    return gate.get("sha256") if isinstance(gate, Mapping) else None


def admit_population(
    prr: PopulationRegistration,
    rows: Iterable[tuple[int, Mapping[str, Any]]],
    conditions: Mapping[str, Any],
) -> Admission:
    """Apply A1-A11 and return the admitted selection plus observed facts.

    `rows` is an iterable of (line number, row). Admission never reads a model field (A10) and never
    writes anything (pure). Any violation raises Stop; there is no partial or best-effort result.
    """
    check_methodology(prr)
    check_authorization(prr)
    check_conditions(prr, conditions)
    check_splits(prr)

    materialized = list(rows)
    selected: dict[str, list[tuple[int, Mapping[str, Any]]]] = {arm.arm_id: [] for arm in prr.arms}
    families = {(arm.split, arm.condition) for arm in prr.arms}

    for number, row in materialized:
        _require(isinstance(row, Mapping), f"A6: line {number}: row must be a mapping")
        # A candidate is any row whose (split, condition) matches a declared arm family. The row
        # contract is enforced on every candidate BEFORE the gate is read, so a malformed row cannot
        # silently drop out of selection by failing to produce a gate sha.
        family = (row.get("split"), row.get("condition"))
        if family not in families:
            continue
        candidate_arms = [arm for arm in prr.arms if (arm.split, arm.condition) == family]
        check_row_contract(candidate_arms[0].arm_id, number, row)
        for arm in candidate_arms:
            # A9: within a family the gate sha discriminates. An unregistered gate matches no arm and
            # is therefore invisible, which is the intended treatment of an unregistered arm.
            if _row_gate(row) == arm.gate_sha256:
                selected[arm.arm_id].append((number, row))

    observations: list[ArmObservation] = []
    for arm in prr.arms:
        arm_rows = selected[arm.arm_id]
        # A7
        _require(len(arm_rows) == prr.expected_rows_per_arm,
                 f"A7: {arm.arm_id}: {len(arm_rows)} rows selected, expected {prr.expected_rows_per_arm}")
        # A8
        tasks = [row["task"] for _, row in arm_rows]
        _require(len(set(tasks)) == len(tasks), f"A8: {arm.arm_id}: duplicate task rows")
        _require(set(tasks) == set(prr.task_set), f"A8: {arm.arm_id}: task set differs from the declared task_set")

        arm_solvable = [row for _, row in arm_rows if row.get("expected_outcome") == "verified_done"]
        arm_unsuccessful = [row for row in arm_solvable if row.get("oracle_passed") is not True]
        observations.append(ArmObservation(
            arm_id=arm.arm_id,
            rows=tuple(arm_rows),
            solvable=len(arm_solvable),
            unsuccessful_solvable=len(arm_unsuccessful),
        ))

    total_rows = sum(len(obs.rows) for obs in observations)
    _require(total_rows == prr.expected_total_rows,
             f"A7: {total_rows} rows selected in total, expected {prr.expected_total_rows}")

    observed_solvable = sum(obs.solvable for obs in observations)
    observed_unsuccessful = sum(obs.unsuccessful_solvable for obs in observations)

    if prr.historical_assertions is not None:
        expectations = prr.historical_assertions
        if "solvable" in expectations:
            _require(observed_solvable == expectations["solvable"],
                     f"historical reproduction: solvable {observed_solvable} != {expectations['solvable']}")
        if "unsuccessful_solvable" in expectations:
            _require(observed_unsuccessful == expectations["unsuccessful_solvable"],
                     f"historical reproduction: unsuccessful_solvable {observed_unsuccessful} "
                     f"!= {expectations['unsuccessful_solvable']}")
        if "unsuccessful_per_arm" in expectations:
            for obs in observations:
                _require(obs.unsuccessful_solvable == expectations["unsuccessful_per_arm"],
                         f"historical reproduction: {obs.arm_id} unsuccessful_solvable "
                         f"{obs.unsuccessful_solvable} != {expectations['unsuccessful_per_arm']}")

    return Admission(
        population_id=prr.population_id,
        arms=tuple(observations),
        total_rows=total_rows,
        observed_solvable=observed_solvable,
        observed_unsuccessful_solvable=observed_unsuccessful,
        selection={obs.arm_id: obs.rows for obs in observations},
    )


# ============================================================================= historical PRR

#: The six MNT-07 arms, reproduced from the frozen runner's population definition so the same rows
#: are selected, not a new population. Historical post-execution facts appear only here.
HISTORICAL_MNT07_DEV_RECORD: dict[str, Any] = {
    "population_id": "HISTORICAL_MNT07_DEV",
    "methodology": dict(FROZEN_METHODOLOGY),
    "new_data_application": False,
    "arms": [
        {"arm_id": "exp22_drift", "role": "primary", "condition": "qwen_selectorkind",
         "gate_sha256": "13e9a05bef83e51bdeb8acc4119f8db8e9755c5850ebfea6f9755fe32654a218", "split": "dev"},
        {"arm_id": "exp18_treatment", "role": "identity", "condition": "qwen_selectorkind",
         "gate_sha256": "dcca9c02e0aee827005043ca08b4b617d4f88c7a3a048b69a975f20572f51e47", "split": "dev"},
        {"arm_id": "exp20_drift", "role": "identity", "condition": "qwen_selectorkind",
         "gate_sha256": "ba0790c8e96b4ec2cb8dff5dd099981fae1d5aae8a1cb4c281dbd463938e29d4", "split": "dev"},
        {"arm_id": "exp20_treatment", "role": "perturbation", "condition": "qwen_astnoop",
         "gate_sha256": "ba0790c8e96b4ec2cb8dff5dd099981fae1d5aae8a1cb4c281dbd463938e29d4", "split": "dev"},
        {"arm_id": "exp21_treatment", "role": "perturbation", "condition": "qwen_donelatch",
         "gate_sha256": "b7bb6338179aad39c4181ad8ca6f4cbaf02ca9f1c6b12aa9261e9c1b8bd748f6", "split": "dev"},
        {"arm_id": "exp22_treatment", "role": "perturbation", "condition": "qwen_formatcontract",
         "gate_sha256": "13e9a05bef83e51bdeb8acc4119f8db8e9755c5850ebfea6f9755fe32654a218", "split": "dev"},
    ],
    "task_set": [
        "config_add_feature", "config_database_host", "config_database_password",
        "config_file_overrides_defaults", "config_service_port", "inventory_find_missing",
        "inventory_low_stock_equal", "inventory_supplier_discount", "inventory_total_value",
        "inventory_update_qty", "mathlib_add_power", "mathlib_divide_zero", "mathlib_fix_subtract",
        "mathlib_median_even", "mathlib_rounding_policy", "textkit_cli_upper",
        "textkit_slug_punctuation", "textkit_slug_spaces", "textkit_style_guide",
        "textkit_truncate_limit",
    ],
    "expected_rows_per_arm": 20,
    "expected_total_rows": 120,
    "input_contract_version": INPUT_CONTRACT_V1,
    "registration_ref": {
        "gate_sha256": "13e9a05bef83e51bdeb8acc4119f8db8e9755c5850ebfea6f9755fe32654a218",
        "commit": "f30c5f6fee287774345e701041899668aaa3ec5d",
    },
    "historical_assertions": {"solvable": 96, "unsuccessful_solvable": 78, "unsuccessful_per_arm": 13},
}


def historical_population() -> PopulationRegistration:
    """The single built-in PRR. Admitted without new-data application, because it is not new data."""
    return load_prr(HISTORICAL_MNT07_DEV_RECORD)
