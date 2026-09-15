"""Deterministic research-state validator for RESEARCH_YIELD.md, EXPERIMENT_LOG.md, DECISIONS.md, PROJECT_TRACKING.md.

Rules (errors are tagged R1..R10):
  R1  completed experiment without research closure (row not closed, missing updates/decision, unknown update IDs,
      missing Research Delta where required, a frozen-gate verdict section in the log with no registry row)
  R2  knowledge record with a settled status but no (or unknown) supporting evidence; missing required fields
  R3  decision citing a nonexistent ID, citing refuted evidence as support, or mislabeling support as refuted
  R4  confounded evidence cited by an affirmative/settled record without a qualification naming each confound
  R5  superseded/falsified/closed ID shown as active; SUPERSEDED record without a valid superseded_by
  R6  experiment registered after a prior experiment that has no closure (unless parallel = yes)
  R7  pending-decision / tracking statements contradicted by the registry (stale "no next gate registered",
      stale ACTIVE GATE, LAST COMPLETED GATE not unique or not the latest)
  R8  experiment testing an already-closed hypothesis without an explicitly changed condition
  R9  invalid verdict classification (verdict not PASS/FAIL/INCONCLUSIVE/PENDING, frozen gate without gate file or
      verdict section, no_gate not INCONCLUSIVE, gate file with no registry row, PENDING not last/open)
  R10 current research question not traceable to prior evidence

Usage:  .venv\\Scripts\\python.exe scripts\\validate_research_state.py [root]
Exit code 0 when no errors, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

RECORD_KINDS = ("CAP", "CON", "METH", "H", "Q")
REQUIRED_KEYS = ("status", "evidence", "contradicted_by", "scope", "establishes", "not_established", "consequence",
                 "redundant", "supersedes", "next")
STATUSES = {
    "CAP": {"SUPPORTED", "PARTIALLY_SUPPORTED", "SUPERSEDED"},
    "CON": {"SUPPORTED", "PARTIALLY_SUPPORTED", "SUPERSEDED"},
    "METH": {"SUPPORTED", "PARTIALLY_SUPPORTED", "SUPERSEDED"},
    "H": {"OPEN", "SUPPORTED", "PARTIALLY_SUPPORTED", "FALSIFIED", "SUPERSEDED"},
    "Q": {"OPEN", "DEFERRED", "CLOSED"},
}
SETTLED = {"SUPPORTED", "PARTIALLY_SUPPORTED", "FALSIFIED", "SUPERSEDED"}
INACTIVE = {"FALSIFIED", "SUPERSEDED", "CLOSED"}
CLOSED_H = {"SUPPORTED", "FALSIFIED"}
VERDICTS = {"PASS", "PARTIAL", "FAIL", "INCONCLUSIVE", "PENDING"}
SPLITS = {"dev", "heldout", "other"}
CONFIDENCE = {"mechanism-valid", "dev-supported", "heldout-supported"}
AUDIT_LABELS = ("DIRECTION", "POPULATION", "COMPARISONS", "DESCRIPTIVE VS GATE", "CONFOUNDS", "CAUSAL LANGUAGE", "NARROW FINDINGS", "NARROW PASS")
DELTA_LABELS = ("BEFORE", "RESULT", "LEARNED", "NOT LEARNED", "UPDATED", "SYSTEM CONSEQUENCE", "ELIMINATED WORK", "NEXT UNCERTAINTY")
ID_RE = re.compile(r"\b(?:CAP|CON|METH|H|Q|EXP|FND|MNT)-\d{2,3}\b")


@dataclass
class Row:
    cells: dict[str, str]
    order: int

    def get(self, key: str) -> str:
        return self.cells.get(key, "").strip()


@dataclass
class Record:
    rid: str
    kind: str
    fields: dict[str, str] = field(default_factory=dict)


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else ""


def _table(section: str, first_column_prefixes: tuple[str, ...]) -> list[dict[str, str]]:
    lines = [line for line in section.splitlines() if line.startswith("|")]
    if not lines:
        return []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and cells[0].startswith(first_column_prefixes):
            rows.append(dict(zip(header, cells)))
    return rows


def _ids(value: str) -> list[str]:
    return ID_RE.findall(value or "")


def parse_records(text: str) -> dict[str, Record]:
    records: dict[str, Record] = {}
    current: Record | None = None
    for line in text.splitlines():
        heading = re.match(r"^### ((CAP|CON|METH|H|Q)-\d{3}) — ", line)
        if heading:
            current = Record(heading.group(1), heading.group(2))
            records[current.rid] = current
            continue
        if line.startswith("### ") or line.startswith("## "):
            current = None
            continue
        entry = re.match(r"^- ([a-z_]+): (.*)$", line)
        if current is not None and entry:
            current.fields[entry.group(1)] = entry.group(2).strip()
    return records


def parse_deltas(text: str, kind: str = "Delta") -> dict[str, set[str]]:
    deltas: dict[str, set[str]] = {}
    current = None
    for line in text.splitlines():
        heading = re.match(rf"^### {kind} (EXP-\d{{2,3}})\s*$", line)
        if heading:
            current = heading.group(1)
            deltas[current] = set()
            continue
        if line.startswith("#"):
            current = None
            continue
        entry = re.match(r"^- ([A-Z ]+): \S", line)
        if current and entry:
            deltas[current].add(entry.group(1))
    return deltas


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    ry = (root / "RESEARCH_YIELD.md").read_text(encoding="utf-8")
    log = (root / "EXPERIMENT_LOG.md").read_text(encoding="utf-8")
    decisions = (root / "DECISIONS.md").read_text(encoding="utf-8")
    tracking = (root / "PROJECT_TRACKING.md").read_text(encoding="utf-8")
    gate_dir = root / "benchmark" / "gates"
    gate_files = {p.name for p in gate_dir.glob("*.md")} if gate_dir.is_dir() else set()
    log_headings = [re.sub(r"^#+\s*", "", line).strip() for line in log.splitlines() if line.startswith("#")]

    registry = [Row(cells, i) for i, cells in enumerate(_table(_section(ry, "Experiment registry"), ("EXP-",)))]
    reg_ids = {row.get("ID") for row in registry}
    findings = {r["ID"]: r for r in _table(_section(ry, "Findings and maintenance (not experiments)"), ("FND-", "MNT-"))}
    records = parse_records(ry)
    deltas = parse_deltas(ry)
    audits = parse_deltas(ry, "Audit")
    known = reg_ids | set(findings) | set(records)

    def heading_exists(section: str) -> bool:
        return bool(section) and any(h.startswith(section) for h in log_headings)

    for fid, finding in findings.items():
        if not heading_exists(finding.get("log_section", "")):
            errors.append(f"R2 {fid}: log_section {finding.get('log_section')!r} is not a heading in EXPERIMENT_LOG.md")

    # ---- registry-level rules (R1, R6, R8, R9)
    delta_protocol_started = False
    audit_protocol_started = False
    for row in registry:
        rid, verdict, basis, gate = row.get("ID"), row.get("verdict"), row.get("basis"), row.get("gate")
        if not heading_exists(row.get("log_section")):
            errors.append(f"R1 {rid}: log_section {row.get('log_section')!r} is not a heading in EXPERIMENT_LOG.md")
        if verdict not in VERDICTS:
            errors.append(f"R9 {rid}: verdict {verdict!r} is not PASS/PARTIAL/FAIL/INCONCLUSIVE/PENDING")
        if row.get("split") not in SPLITS:
            errors.append(f"R9 {rid}: split {row.get('split')!r} is not dev/heldout/other")
        if verdict == "PARTIAL" and basis != "frozen_gate":
            errors.append(f"R9 {rid}: PARTIAL is only defined by a frozen gate")
        if basis == "frozen_gate":
            if gate not in gate_files:
                errors.append(f"R9 {rid}: frozen_gate basis but gate file {gate!r} does not exist")
            if verdict != "PENDING" and "gate verdict" not in row.get("log_section"):
                errors.append(f"R9 {rid}: frozen_gate verdict must cite the '— gate verdict' section")
        elif basis == "no_gate" and verdict != "INCONCLUSIVE":
            errors.append(f"R9 {rid}: no_gate experiments must be classified INCONCLUSIVE")
        elif basis not in ("frozen_gate", "no_gate", "stated_criterion"):
            errors.append(f"R9 {rid}: unknown basis {basis!r}")
        if verdict == "PENDING":
            if row.get("closure") != "open":
                errors.append(f"R9 {rid}: PENDING experiment must have closure 'open'")
            if row.order != len(registry) - 1 and row.get("parallel") != "yes":
                errors.append(f"R9 {rid}: PENDING experiment must be the last registered unless parallel")
            continue
        if row.get("closure") != "closed" or not row.get("updates") or not row.get("decision"):
            errors.append(f"R1 {rid}: completed ({verdict}) but research closure is missing")
        for uid in _ids(row.get("updates")):
            if uid not in known:
                errors.append(f"R1 {rid}: update {uid} does not exist")
        if row.get("delta") == "yes":
            delta_protocol_started = True
            missing = [label for label in DELTA_LABELS if label not in deltas.get(rid, set())]
            if missing:
                errors.append(f"R1 {rid}: Research Delta missing {', '.join(missing)}")
        elif delta_protocol_started:
            errors.append(f"R1 {rid}: completed after the delta protocol started but has no Research Delta")
        if row.get("audit") == "yes":
            audit_protocol_started = True
            missing = [label for label in AUDIT_LABELS if label not in audits.get(rid, set())]
            if missing:
                errors.append(f"R1 {rid}: Semantic Audit missing {', '.join(missing)}")
        elif audit_protocol_started:
            errors.append(f"R1 {rid}: completed after the audit protocol started but has no Semantic Audit")
    for row in registry:
        if row.get("closure") != "closed" and row.get("parallel") != "yes":
            for later in registry[row.order + 1:]:
                if later.get("parallel") != "yes":
                    errors.append(f"R6 {later.get('ID')}: registered while {row.get('ID')} has no closure")
    registered_gates = {row.get("gate") for row in registry}
    for name in sorted(gate_files - registered_gates):
        errors.append(f"R9 gate {name}: registered experiment (gate file) has no registry row / verdict")
    for heading in log_headings:
        if heading.endswith("gate verdict (as pre-registered, unmodified)") or heading.endswith("gate verdict (frozen scorer, unmodified)"):
            prefix = heading.split(" — ")[0]
            if not any(row.get("log_section").startswith(prefix) for row in registry):
                errors.append(f"R1 log section {heading!r}: completed experiment has no registry row")
    for rid, rec in records.items():
        if rec.kind == "H" and rec.fields.get("status") in CLOSED_H:
            closer = rec.fields.get("closed_by", "")
            closer_rows = [row for row in registry if row.get("ID") == closer]
            if not closer_rows:
                errors.append(f"R8 {rid}: closed hypothesis needs closed_by naming a registry experiment")
                continue
            for later in registry[closer_rows[0].order + 1:]:
                if rid in _ids(later.get("tests")) and later.get("changed_condition") in ("", "-", "none"):
                    errors.append(f"R8 {later.get('ID')}: retests closed {rid} without an explicitly changed condition")

    # ---- record-level rules (R2, R4, R5, R10)
    confounds = {row.get("ID"): [c for c in _ids(row.get("confounds"))] for row in registry}
    for rid, rec in records.items():
        for key in REQUIRED_KEYS:
            if key not in rec.fields or not rec.fields[key]:
                errors.append(f"R2 {rid}: missing field {key}")
        status = rec.fields.get("status", "")
        if status not in STATUSES[rec.kind]:
            errors.append(f"R2 {rid}: status {status!r} not allowed for {rec.kind}")
        evidence = _ids(rec.fields.get("evidence", ""))
        if status in SETTLED and not evidence:
            errors.append(f"R2 {rid}: {status} record has no supporting evidence")
        if rec.kind in ("CAP", "CON", "H") and status in {"SUPPORTED", "PARTIALLY_SUPPORTED", "FALSIFIED"}:
            confidence = rec.fields.get("confidence", "")
            if confidence not in CONFIDENCE:
                errors.append(f"R2 {rid}: confidence {confidence!r} must be mechanism-valid, dev-supported or heldout-supported")
            elif confidence == "heldout-supported" and not any(row.get("split") == "heldout" and row.get("ID") in evidence for row in registry):
                errors.append(f"R2 {rid}: heldout-supported without heldout registry evidence")
        for eid in evidence:
            if eid not in reg_ids and eid not in findings:
                errors.append(f"R2 {rid}: evidence {eid} is not a registry experiment or finding")
        if status in SETTLED:
            needed = sorted({c for eid in evidence for c in confounds.get(eid, [])})
            qualification = rec.fields.get("qualification", "")
            missing = [c for c in needed if c not in qualification]
            if missing:
                errors.append(f"R4 {rid}: cites confounded evidence without a qualification naming {', '.join(missing)}")
        if status == "SUPERSEDED":
            successors = _ids(rec.fields.get("superseded_by", ""))
            if not successors or any(s not in records for s in successors):
                errors.append(f"R5 {rid}: SUPERSEDED record needs superseded_by naming existing records")
        for ref in _ids(rec.fields.get("next", "")):
            if ref not in records:
                errors.append(f"R10 {rid}: next {ref} does not exist")
        if rec.kind == "Q":
            sources = _ids(rec.fields.get("derived_from", ""))
            if not sources or any(s not in known for s in sources):
                errors.append(f"R10 {rid}: question must be derived_from existing evidence or knowledge IDs")
    active = _section(ry, "Active research state")
    for aid in _ids(active):
        if aid in reg_ids:
            if next(row for row in registry if row.get("ID") == aid).get("closure") != "open":
                errors.append(f"R5 active state lists {aid}, which is already closed")
            continue
        rec = records.get(aid)
        if rec is None:
            errors.append(f"R5 active state lists {aid}, which does not exist")
        elif rec.fields.get("status") in INACTIVE:
            errors.append(f"R5 active state lists {aid} with status {rec.fields.get('status')}")

    # ---- decisions (R3, R7)
    decision_rows = _table(_section(decisions, "Current state"), ("",))
    for row in decision_rows:
        mechanism = row.get("Mechanism", "")
        if not mechanism or mechanism.startswith("---"):
            continue
        cell = row.get("Knowledge", "")
        state = row.get("State", "")
        if any(marker in state for marker in ("**on**", "**available**", "PASSED")) and not re.search(r"\b(?:CAP|CON|METH|H|Q)-\d{3}\b", cell):
            errors.append(f"R3 active decision {mechanism!r}: cites no knowledge ID")
        for match in re.finditer(r"\b((?:CAP|CON|METH|H|Q)-\d{3})(\(refuted\))?", cell):
            kid, refuted = match.group(1), bool(match.group(2))
            rec = records.get(kid)
            if rec is None:
                errors.append(f"R3 decision {mechanism!r}: cites nonexistent {kid}")
                continue
            status = rec.fields.get("status")
            if not refuted and status in {"FALSIFIED", "SUPERSEDED"}:
                errors.append(f"R3 decision {mechanism!r}: cites {kid} ({status}) as support")
            if refuted and status not in {"FALSIFIED", "SUPERSEDED"}:
                errors.append(f"R3 decision {mechanism!r}: marks {kid} refuted but its status is {status}")
    pending = _section(decisions, "Pending decision")
    last_gate = registry[-1].get("gate") if registry else ""
    last_stem = last_gate.removesuffix(".md")
    for line in pending.splitlines():
        if not line.startswith("- ") or line.startswith("- [Superseded"):
            continue
        for kid in re.findall(r"\b(?:CAP|CON|METH|H|Q)-\d{3}\b", line):
            if kid not in records:
                errors.append(f"R3 pending decision cites nonexistent {kid}")
        if "no next gate registered" in line and last_stem and last_stem not in line:
            errors.append(f"R7 pending decision says 'no next gate registered' but the latest registered experiment is {last_stem}: {line[:80]!r}")
    last_lines = [line for line in tracking.splitlines() if line.startswith("LAST COMPLETED GATE:")]
    if len(last_lines) > 1:
        errors.append(f"R7 PROJECT_TRACKING has {len(last_lines)} 'LAST COMPLETED GATE' lines; only one can be last")
    closed_stems = {row.get("gate").removesuffix(".md") for row in registry if row.get("closure") == "closed"}
    completed_frozen = [row for row in registry if row.get("basis") == "frozen_gate" and row.get("closure") == "closed"]
    if last_lines and completed_frozen and completed_frozen[-1].get("gate").removesuffix(".md") not in last_lines[-1]:
        errors.append(f"R7 LAST COMPLETED GATE does not name the latest completed gate {completed_frozen[-1].get('gate')}")
    for line in tracking.splitlines():
        if line.startswith("ACTIVE GATE:"):
            named = re.match(r"ACTIVE GATE:\s*([A-Za-z0-9_.-]+)", line)
            stem = named.group(1).removesuffix(".md") if named else ""
            if stem in closed_stems:
                errors.append(f"R7 PROJECT_TRACKING 'ACTIVE GATE' names {stem}, which is already closed")
            elif stem not in {row.get("gate").removesuffix(".md") for row in registry if row.get("closure") == "open"}:
                errors.append(f"R7 PROJECT_TRACKING 'ACTIVE GATE' names {stem!r}, which is not an open registered experiment")
        if line.startswith("NEXT GATE:"):
            if "none registered" in line and any(row.get("verdict") == "PENDING" for row in registry):
                errors.append("R7 NEXT GATE says none registered while a PENDING experiment is registered")
            qids = re.findall(r"\bQ-\d{3}\b", line)
            if not qids:
                errors.append("R10 NEXT GATE line cites no research question (Q-ID)")
            for qid in qids:
                rec = records.get(qid)
                if rec is None or rec.fields.get("status") not in {"OPEN", "DEFERRED"}:
                    errors.append(f"R10 NEXT GATE cites {qid}, which is not an open or deferred question")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    errors = validate(root)
    for error in errors:
        print(error)
    print(f"research state: {'OK' if not errors else f'{len(errors)} error(s)'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
