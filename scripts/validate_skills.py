"""Validate the reusable-skill infrastructure (skills/registry.yaml and skills/*/SKILL.md).

Structural rules (each error is tagged S1..S12; any error exits non-zero):
  S1  skills/registry.yaml exists
  S2  registry parses under the strict YAML subset documented in the registry header (malformed -> error)
  S3  every registry entry has exactly the keys id, version, path, purpose, applies_when, does_not_apply_when;
      scalars are non-empty; the two lists are non-empty; version is a positive integer; id is kebab-case
  S4  skill ids are unique
  S5  registry paths are unique, relative, inside skills/, and named <id>/SKILL.md
  S6  every registered path exists
  S7  every SKILL.md has front matter with id and version
  S8  SKILL.md front matter id and version agree with the registry entry
  S9  every SKILL.md has each required contract section exactly once, non-empty
  S10 the procedure section contains at least three numbered steps
  S11 related_CAP_CON_METH_records cites only CAP/CON/METH IDs that exist as headings in RESEARCH_YIELD.md
  S12 no SKILL.md under skills/ is absent from the registry (orphan)

Dependency-free on purpose: the CI project-validation job installs nothing.

Usage:  python scripts/validate_skills.py [repo_root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ENTRY_KEYS = ("id", "version", "path", "purpose", "applies_when", "does_not_apply_when")
LIST_KEYS = {"applies_when", "does_not_apply_when"}
SECTIONS = ("purpose", "applies_when", "does_not_apply_when", "required_inputs", "preconditions", "procedure", "invariants",
            "acceptance_criteria", "evidence_to_record", "failure_modes", "related_CAP_CON_METH_records")
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RECORD_PATTERN = re.compile(r"\b([A-Z]+)-(\d{3})\b")
ALLOWED_RECORD_PREFIXES = {"CAP", "CON", "METH"}
MIN_PROCEDURE_STEPS = 3


class RegistryFormatError(ValueError):
    """The registry is not valid under the supported YAML subset."""


def _scalar(text: str, lineno: int) -> str:
    value = text.strip()
    if value[:1] in ("'", '"'):
        if len(value) < 2 or value[-1] != value[0]:
            raise RegistryFormatError(f"line {lineno}: unterminated quoted value")
        value = value[1:-1]
    elif value[:1] in ("[", "{", "&", "*", "|", ">", "!"):
        raise RegistryFormatError(f"line {lineno}: unsupported YAML construct {value[:1]!r}")
    return value


def _key_value(text: str, lineno: int) -> tuple[str, str]:
    if ":" not in text:
        raise RegistryFormatError(f"line {lineno}: expected 'key: value'")
    key, _, rest = text.partition(":")
    key = key.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise RegistryFormatError(f"line {lineno}: invalid key {key!r}")
    if rest and not rest.startswith(" "):
        raise RegistryFormatError(f"line {lineno}: expected a space after ':'")
    return key, rest


def parse_registry(text: str) -> list[dict[str, Any]]:
    """Parse the strict subset: a top-level `skills:` list of mappings with scalar values and scalar lists."""
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    open_list: str | None = None
    seen_root = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise RegistryFormatError(f"line {lineno}: tab characters are not allowed")
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw.strip()
        if indent == 0:
            if seen_root or body != "skills:":
                raise RegistryFormatError(f"line {lineno}: the only top-level key is 'skills:'")
            seen_root = True
            continue
        if not seen_root:
            raise RegistryFormatError(f"line {lineno}: content before 'skills:'")
        if indent == 2:
            if not body.startswith("- "):
                raise RegistryFormatError(f"line {lineno}: expected '- id: ...' to start an entry")
            key, rest = _key_value(body[2:], lineno)
            current = {}
            entries.append(current)
            open_list = None
            if not rest.strip():
                raise RegistryFormatError(f"line {lineno}: an entry must start with a scalar key")
            current[key] = _scalar(rest, lineno)
        elif indent == 4:
            if current is None:
                raise RegistryFormatError(f"line {lineno}: key outside an entry")
            key, rest = _key_value(body, lineno)
            if key in current:
                raise RegistryFormatError(f"line {lineno}: duplicate key {key!r}")
            if rest.strip():
                current[key] = _scalar(rest, lineno)
                open_list = None
            else:
                current[key] = []
                open_list = key
        elif indent == 6:
            if current is None or open_list is None or not body.startswith("- "):
                raise RegistryFormatError(f"line {lineno}: list item without an open list key")
            current[open_list].append(_scalar(body[2:], lineno))
        else:
            raise RegistryFormatError(f"line {lineno}: unexpected indentation ({indent} spaces)")
    if not seen_root:
        raise RegistryFormatError("missing top-level 'skills:'")
    return entries


def parse_skill(text: str) -> tuple[dict[str, str], dict[str, list[str]], list[str]]:
    """Return (front matter, sections -> body lines, structural problems)."""
    problems: list[str] = []
    lines = text.splitlines()
    front: dict[str, str] = {}
    start = 0
    if lines and lines[0].strip() == "---":
        try:
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        except StopIteration:
            problems.append("front matter is not closed with '---'")
            end = 0
        for line in lines[1:end]:
            if line.strip():
                key, _, value = line.partition(":")
                front[key.strip()] = value.strip()
        start = end + 1
    else:
        problems.append("missing front matter ('---' block with id and version)")
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[start:]:
        match = re.match(r"^##\s+(\S.*?)\s*$", line)
        if match and not line.startswith("###"):
            current = match.group(1)
            if current in sections:
                problems.append(f"section {current!r} appears more than once")
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return front, sections, problems


def research_record_ids(root: Path) -> set[str]:
    path = root / "RESEARCH_YIELD.md"
    if not path.is_file():
        return set()
    return set(re.findall(r"^### ((?:CAP|CON|METH|H|Q)-\d{3})\b", path.read_text(encoding="utf-8"), flags=re.MULTILINE))


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    skills_dir = root / "skills"
    registry_path = skills_dir / "registry.yaml"
    if not registry_path.is_file():
        return ["S1 skills/registry.yaml does not exist"]
    try:
        entries = parse_registry(registry_path.read_text(encoding="utf-8"))
    except RegistryFormatError as exc:
        return [f"S2 registry.yaml is malformed: {exc}"]
    if not entries:
        errors.append("S3 registry.yaml registers no skills")
    records = research_record_ids(root)
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    registered_files: set[Path] = set()
    for index, entry in enumerate(entries):
        label = f"entry {index} ({entry.get('id', '?')})"
        missing = [k for k in ENTRY_KEYS if k not in entry]
        unknown = [k for k in entry if k not in ENTRY_KEYS]
        if missing:
            errors.append(f"S3 {label}: missing keys {missing}")
        if unknown:
            errors.append(f"S3 {label}: unknown keys {unknown}")
        for key in ENTRY_KEYS:
            if key not in entry:
                continue
            value = entry[key]
            if key in LIST_KEYS:
                if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
                    errors.append(f"S3 {label}: {key} must be a non-empty list of non-empty items")
            elif not isinstance(value, str) or not value.strip():
                errors.append(f"S3 {label}: {key} must be a non-empty scalar")
        skill_id = entry.get("id") if isinstance(entry.get("id"), str) else ""
        if skill_id and not ID_PATTERN.match(skill_id):
            errors.append(f"S3 {label}: id {skill_id!r} is not kebab-case")
        version = entry.get("version")
        if isinstance(version, str) and version.strip() and not re.fullmatch(r"[1-9]\d*", version.strip()):
            errors.append(f"S3 {label}: version {version!r} is not a positive integer")
        if skill_id:
            if skill_id in seen_ids:
                errors.append(f"S4 duplicate skill id {skill_id!r}")
            seen_ids.add(skill_id)
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        if path in seen_paths:
            errors.append(f"S5 duplicate registry path {path!r}")
        seen_paths.add(path)
        rel = Path(path)
        if rel.is_absolute() or ".." in rel.parts:
            errors.append(f"S5 {label}: path {path!r} must be relative and inside skills/")
            continue
        if skill_id and rel.as_posix() != f"{skill_id}/SKILL.md":
            errors.append(f"S5 {label}: path {path!r} must be {skill_id}/SKILL.md")
        skill_file = skills_dir / rel
        if not skill_file.is_file():
            errors.append(f"S6 {label}: registered path {path!r} does not exist")
            continue
        registered_files.add(skill_file.resolve())
        front, sections, problems = parse_skill(skill_file.read_text(encoding="utf-8"))
        errors.extend(f"S9 {path}: {p}" for p in problems)
        if "id" not in front or not front["id"]:
            errors.append(f"S7 {path}: front matter has no id")
        elif skill_id and front["id"] != skill_id:
            errors.append(f"S8 {path}: SKILL.md id {front['id']!r} != registry id {skill_id!r}")
        if "version" not in front or not front["version"]:
            errors.append(f"S7 {path}: front matter has no version")
        elif isinstance(version, str) and front["version"] != version.strip():
            errors.append(f"S8 {path}: SKILL.md version {front['version']!r} != registry version {version!r}")
        for section in SECTIONS:
            if section not in sections:
                errors.append(f"S9 {path}: missing required section {section!r}")
            elif not any(line.strip() for line in sections[section]):
                errors.append(f"S9 {path}: section {section!r} is empty")
        steps = [line for line in sections.get("procedure", []) if re.match(r"^\s*\d+\.\s+\S", line)]
        if "procedure" in sections and len(steps) < MIN_PROCEDURE_STEPS:
            errors.append(f"S10 {path}: procedure has {len(steps)} numbered steps (at least {MIN_PROCEDURE_STEPS} required)")
        for prefix, number in RECORD_PATTERN.findall("\n".join(sections.get("related_CAP_CON_METH_records", []))):
            record = f"{prefix}-{number}"
            if prefix not in ALLOWED_RECORD_PREFIXES:
                errors.append(f"S11 {path}: {record} is not a CAP/CON/METH record")
            elif record not in records:
                errors.append(f"S11 {path}: {record} does not exist in RESEARCH_YIELD.md")
    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        if skill_file.resolve() not in registered_files:
            errors.append(f"S12 orphan skill {skill_file.relative_to(skills_dir).as_posix()} is not in registry.yaml")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    errors = validate(root)
    for error in errors:
        print(error)
    count = len(parse_registry((root / "skills" / "registry.yaml").read_text(encoding="utf-8"))) if not errors else 0
    print(f"skills: {'OK (' + str(count) + ' registered)' if not errors else f'{len(errors)} error(s)'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
