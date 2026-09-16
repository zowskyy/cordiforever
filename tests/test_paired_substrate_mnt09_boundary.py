"""Ownership-boundary tests: MNT-09 is the ONLY population-admission authority.

`paired_substrate_v1` must not create a second interpretation of population validity. Its
responsibility begins only after MNT-09 admission succeeds.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import paired_substrate_v1 as ps  # noqa: E402
from benchmark.analysis import taxonomy_population_registry_v1 as mnt09  # noqa: E402
from tests import conftest_paired_fixtures as fx  # noqa: E402

INC, CHAL = "inc_arm", "chal_arm"
INC_COND, CHAL_COND = "synthetic_incumbent", "synthetic_challenger"

SOURCE = (ROOT / "benchmark" / "analysis" / "paired_substrate_v1.py").read_text(encoding="utf-8")


@pytest.fixture()
def conditions():
    return fx.conditions_with(INC_COND, CHAL_COND)


def test_raw_row_list_is_rejected(conditions):
    rows = [(1, fx.row(fx.TASKS[0], condition=INC_COND, gate=fx.INC_GATE,
                       harness=fx.HARNESS_OLD, oracle_passed=False))]
    with pytest.raises(ps.PairedError, match="does not admit populations and never accepts raw rows"):
        ps.selection_from_admission(rows, INC)


class DuckTypedAdmission:
    """Looks exactly like an Admission by attribute, but is not one. Must still be refused."""

    def __init__(self, arm_id: str, rows):
        self.population_id = "IMPOSTOR"
        self.selection = {arm_id: rows}
        self.arms = ()
        self.total_rows = len(rows)
        self.observed_solvable = 0
        self.observed_unsuccessful_solvable = 0


@pytest.mark.parametrize("impostor", [None, {}, [], "admission", 42, {"selection": {"inc_arm": []}}])
def test_anything_that_is_not_an_mnt09_admission_is_rejected(impostor):
    with pytest.raises(ps.PairedError, match="Admission"):
        ps.selection_from_admission(impostor, INC)


def test_duck_typed_admission_lookalike_is_rejected(conditions):
    """Admission is identified by TYPE, not by shape: a structural look-alike must not pass."""
    rows = [(1, fx.row(fx.TASKS[0], condition=INC_COND, gate=fx.INC_GATE,
                       harness=fx.HARNESS_OLD, oracle_passed=False))]
    with pytest.raises(ps.PairedError, match="Admission"):
        ps.selection_from_admission(DuckTypedAdmission(INC, rows), INC)


def test_admission_from_mnt09_is_accepted(conditions):
    admission = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    selection = ps.selection_from_admission(admission, INC)
    assert set(selection.rows) == set(fx.TASKS)


def test_an_arm_mnt09_refuses_never_reaches_the_paired_module(conditions):
    """MNT-09 rejects the population, so no Admission exists for the paired module to consume."""
    bad = fx.prr("POP_BAD", "bad_arm", "condition_that_does_not_exist", fx.INC_GATE)
    registration = mnt09.load_prr(bad)
    rows = [(i, fx.row(t, condition="condition_that_does_not_exist", gate=fx.INC_GATE,
                       harness=fx.HARNESS_OLD, oracle_passed=False))
            for i, t in enumerate(fx.TASKS, start=1)]
    with pytest.raises(mnt09.Stop, match="A4"):
        mnt09.admit_population(registration, rows, conditions)


def test_heldout_is_blocked_at_the_mnt09_layer_before_the_paired_module(conditions):
    record = fx.prr("POP_HELDOUT", INC, INC_COND, fx.INC_GATE)
    record["arms"][0]["split"] = "heldout"
    registration = mnt09.load_prr(record)
    rows = [(i, fx.row(t, condition=INC_COND, gate=fx.INC_GATE, harness=fx.HARNESS_OLD,
                       oracle_passed=False, split="heldout"))
            for i, t in enumerate(fx.TASKS, start=1)]
    with pytest.raises(mnt09.Stop, match="A5"):
        mnt09.admit_population(registration, rows, conditions)


def test_paired_module_performs_no_population_filtering():
    """No split/condition/gate/arm selection logic may exist in this module."""
    forbidden = (
        r'row\.get\("split"\)\s*==\s*arm',
        r'row\.get\("condition"\)\s*==',
        r'gate_sha256',
        r'PERMITTED_SPLITS',
        r'experiment.*gate.*sha256.*==',
    )
    for pattern in forbidden:
        assert re.search(pattern, SOURCE) is None, f"population filtering leaked in: {pattern}"


def test_paired_module_does_not_import_a_second_admission_path():
    """It imports MNT-09 and uses it; it defines no admit/select of its own."""
    assert "taxonomy_population_registry_v1 as mnt09" in SOURCE
    assert "def admit_population" not in SOURCE
    assert "def select_arms" not in SOURCE
    assert "def admit" not in SOURCE


def test_only_the_split_defence_in_depth_check_remains(conditions):
    """The module keeps exactly one split assertion, as defence in depth, and it only ever
    asserts 'dev' -- it can never widen what MNT-09 permits."""
    occurrences = re.findall(r'"split"', SOURCE)
    assert len(occurrences) == 1
    assert '!= "dev"' in SOURCE or '== "dev"' in SOURCE
    assert "heldout" not in SOURCE.replace("# ", "").lower() or 'split.*heldout' not in SOURCE


def test_admission_objects_carry_the_population_identity(conditions):
    admission = fx.admit(INC, INC_COND, fx.INC_GATE, fx.HARNESS_OLD, [], conditions)
    assert admission.population_id == f"POP_{INC}"
    assert admission.total_rows == len(fx.TASKS)
