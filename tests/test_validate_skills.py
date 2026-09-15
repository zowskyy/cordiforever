from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("validate_skills", ROOT / "scripts" / "validate_skills.py")
vs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vs)

SKILL = """---
id: {id}
version: 1
---

# Skill: {id}

## purpose
Do the thing.

## applies_when
- the thing is needed

## does_not_apply_when
- the thing is not needed

## required_inputs
- an input

## preconditions
- a precondition

## procedure
1. First.
2. Second.
3. Third.

## invariants
- an invariant

## acceptance_criteria
- a criterion

## evidence_to_record
- a record

## failure_modes
- a failure

## related_CAP_CON_METH_records
- METH-003
"""

ENTRY = """  - id: {id}
    version: 1
    path: {id}/SKILL.md
    purpose: Do the thing.
    applies_when:
      - the thing is needed
    does_not_apply_when:
      - the thing is not needed
"""


def make_repo(tmp_path: Path, ids=("alpha", "beta"), entries: str | None = None) -> Path:
    (tmp_path / "RESEARCH_YIELD.md").write_text("# RY\n\n### METH-003 — freeze\n\n### CAP-001 — cap\n", encoding="utf-8")
    skills = tmp_path / "skills"
    skills.mkdir()
    for skill_id in ids:
        (skills / skill_id).mkdir()
        (skills / skill_id / "SKILL.md").write_text(SKILL.format(id=skill_id), encoding="utf-8")
    body = entries if entries is not None else "".join(ENTRY.format(id=i) for i in ids)
    (skills / "registry.yaml").write_text("# comment\nskills:\n" + body, encoding="utf-8")
    return tmp_path


def codes(errors: list[str]) -> set[str]:
    return {e.split()[0] for e in errors}


def test_valid_registry_passes(tmp_path):
    assert vs.validate(make_repo(tmp_path)) == []


def test_real_repository_skills_validate():
    assert vs.validate(ROOT) == []


def test_main_exit_codes(tmp_path, capsys):
    assert vs.main(["x", str(make_repo(tmp_path))]) == 0
    assert "skills: OK (2 registered)" in capsys.readouterr().out
    (tmp_path / "skills" / "beta" / "SKILL.md").unlink()
    assert vs.main(["x", str(tmp_path)]) == 1


def test_missing_registry_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "skills" / "registry.yaml").unlink()
    assert codes(vs.validate(root)) == {"S1"}


def test_missing_skill_file_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "skills" / "beta" / "SKILL.md").unlink()
    assert "S6" in codes(vs.validate(root))


def test_duplicate_skill_id_fails(tmp_path):
    root = make_repo(tmp_path, ids=("alpha",), entries=ENTRY.format(id="alpha") * 2)
    errors = vs.validate(root)
    assert "S4" in codes(errors) and "S5" in codes(errors)


def test_duplicate_path_fails(tmp_path):
    root = make_repo(tmp_path)
    registry = root / "skills" / "registry.yaml"
    registry.write_text(registry.read_text(encoding="utf-8").replace("path: beta/SKILL.md", "path: alpha/SKILL.md"), encoding="utf-8")
    assert "S5" in codes(vs.validate(root))


def test_missing_required_field_fails(tmp_path):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("## invariants\n- an invariant\n\n", ""), encoding="utf-8")
    errors = vs.validate(root)
    assert any(e.startswith("S9") and "invariants" in e for e in errors)


def test_empty_section_fails(tmp_path):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("- a failure\n", ""), encoding="utf-8")
    assert any(e.startswith("S9") and "empty" in e for e in vs.validate(root))


def test_missing_registry_key_fails(tmp_path):
    root = make_repo(tmp_path)
    registry = root / "skills" / "registry.yaml"
    registry.write_text(registry.read_text(encoding="utf-8").replace("    version: 1\n", "", 1), encoding="utf-8")
    assert "S3" in codes(vs.validate(root))


def test_missing_front_matter_version_fails(tmp_path):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("version: 1\n", "", 1), encoding="utf-8")
    assert "S7" in codes(vs.validate(root))


def test_mismatched_skill_id_fails(tmp_path):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("id: alpha", "id: gamma", 1), encoding="utf-8")
    assert "S8" in codes(vs.validate(root))


def test_mismatched_version_fails(tmp_path):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("version: 1", "version: 2", 1), encoding="utf-8")
    assert "S8" in codes(vs.validate(root))


def test_path_not_matching_id_fails(tmp_path):
    root = make_repo(tmp_path)
    shutil.move(str(root / "skills" / "beta"), str(root / "skills" / "other"))
    registry = root / "skills" / "registry.yaml"
    registry.write_text(registry.read_text(encoding="utf-8").replace("path: beta/SKILL.md", "path: other/SKILL.md"), encoding="utf-8")
    assert "S5" in codes(vs.validate(root))


@pytest.mark.parametrize("reference", ["METH-999", "CON-042", "H-012", "Q-002"])
def test_invalid_record_reference_fails(tmp_path, reference):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("- METH-003", f"- METH-003\n- {reference}"), encoding="utf-8")
    assert "S11" in codes(vs.validate(root))


def test_too_few_procedure_steps_fails(tmp_path):
    root = make_repo(tmp_path)
    skill = root / "skills" / "alpha" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("2. Second.\n3. Third.\n", "- Second.\n"), encoding="utf-8")
    assert "S10" in codes(vs.validate(root))


def test_orphan_skill_fails(tmp_path):
    root = make_repo(tmp_path)
    (root / "skills" / "orphan").mkdir()
    (root / "skills" / "orphan" / "SKILL.md").write_text(SKILL.format(id="orphan"), encoding="utf-8")
    errors = vs.validate(root)
    assert codes(errors) == {"S12"} and "orphan/SKILL.md" in errors[0]


@pytest.mark.parametrize("registry", [
    "skills:\n  - id alpha\n",                                         # missing colon
    "skills:\n   - id: alpha\n",                                       # bad indentation
    "skills:\n  - id: alpha\n\tversion: 1\n",                           # leading tab
    "skills:\n  - id: alpha\n    \tversion: 1\n",                       # tab after spaces
    "skills: []\n",                                                    # flow style
    "other:\n  - id: alpha\n",                                         # wrong root
    "skills:\n  - id: alpha\n    applies_when: [a, b]\n",               # flow list
    "skills:\n  - id: 'alpha\n",                                       # unterminated quote
    "skills:\n  - id: alpha\n    purpose: x\n    purpose: y\n",         # duplicate key
    "skills:\n  - id: alpha\n      - orphan item\n",                    # list item without list key
])
def test_malformed_yaml_fails(tmp_path, registry):
    root = make_repo(tmp_path)
    (root / "skills" / "registry.yaml").write_text(registry, encoding="utf-8")
    assert codes(vs.validate(root)) == {"S2"}
