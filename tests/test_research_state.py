"""Research-state validator: a minimal valid fixture passes; one targeted corruption per rule is detected."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_research_state as v  # noqa: E402

LOG = """# EXPERIMENT_LOG
## Baseline measurement (2026-01-01)
### alpha_v1 — gate verdict (frozen scorer, unmodified)
### beta_v1 — gate verdict (frozen scorer, unmodified)
### Finding: a confound
"""

REGISTRY_HEADER = ("| ID | log_section | gate | split | verdict | basis | confounds | tests | changed_condition | parallel | closure | updates | decision | delta | audit |\n"
                   "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")

ROWS = {
    "EXP-01": "| EXP-01 | Baseline measurement | none | dev | INCONCLUSIVE | no_gate | FND-01 | - | - | no | closed | CON-001 | baseline recorded | no | no |",
    "EXP-02": "| EXP-02 | alpha_v1 — gate verdict | alpha_v1.md | dev | FAIL | frozen_gate | none | H-001 | - | no | closed | H-001, CAP-001 | alpha not promoted | no | no |",
    "EXP-03": "| EXP-03 | beta_v1 — gate verdict | beta_v1.md | dev | PASS | frozen_gate | none | H-002 | - | no | closed | H-002, Q-001 | beta passed | yes | yes |",
}


def record(rid, status, evidence="EXP-02", extra="", confidence="dev-supported"):
    return (f"### {rid} — claim\n- status: {status}\n- confidence: {confidence}\n- evidence: {evidence}\n- contradicted_by: none\n- scope: s\n- establishes: e\n"
            f"- not_established: n\n- consequence: c\n- redundant: none\n- supersedes: none\n- next: none\n{extra}")


RECORDS = {
    "CAP-001": record("CAP-001", "SUPPORTED"),
    "CON-001": record("CON-001", "SUPPORTED", "EXP-01", "- qualification: FND-01 constant across arms\n"),
    "H-001": record("H-001", "FALSIFIED", "EXP-02", "- closed_by: EXP-02\n"),
    "H-002": record("H-002", "OPEN", "EXP-03"),
    "Q-001": record("Q-001", "OPEN", "EXP-03", "- derived_from: H-002, EXP-03\n"),
}

DELTA = ("### Delta EXP-03\n- BEFORE: b\n- RESULT: r\n- LEARNED: l\n- NOT LEARNED: n\n- UPDATED: H-002\n- SYSTEM CONSEQUENCE: s\n"
         "- ELIMINATED WORK: e\n- NEXT UNCERTAINTY: Q-001\n")

AUDIT = ("### Audit EXP-03\n- DIRECTION: ok\n- POPULATION: ok\n- COMPARISONS: ok\n- DESCRIPTIVE VS GATE: ok\n- CONFOUNDS: ok\n"
         "- CAUSAL LANGUAGE: ok\n- NARROW FINDINGS: ok\n- NARROW PASS: ok\n")

DECISIONS = """# DECISIONS
## Current state
| Mechanism | Calibration key | State | Kind | Rationale | Evidence | Knowledge |
|---|---|---|---|---|---|---|
| Alpha | `alpha` | **off** | cap | failed | alpha_v1 | CAP-001, H-001(refuted) |
| Beta | `beta` | **passed** | cap | passed | beta_v1 | Q-001 |

## Pending decision
- **After beta_v1 (PASS):** pending replication (Q-001).
- [Superseded] **After alpha_v1:** no next gate registered.

## History
"""

TRACKING = """# PROJECT_TRACKING
```text
COMPLETED GATE: alpha_v1 - FAIL
LAST COMPLETED GATE: beta_v1 - PASS
NEXT GATE: none registered; pending Q-001.
```
"""


def build(tmp_path, rows=None, records=None, delta=DELTA + AUDIT, decisions=DECISIONS, tracking=TRACKING, log=LOG, gates=("alpha_v1.md", "beta_v1.md"),
          active="- open_hypotheses: H-002\n- open_questions: Q-001\n", findings="| FND-01 | Finding: a confound | confound | c |"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows = dict(ROWS if rows is None else rows)
    records = dict(RECORDS if records is None else records)
    ry = ("# RESEARCH_YIELD\n\n## Experiment registry\n\n" + REGISTRY_HEADER + "\n".join(rows.values()) + "\n\n"
          "## Findings and maintenance (not experiments)\n\n| ID | log_section | kind | summary |\n|---|---|---|---|\n" + findings + "\n\n"
          "## Knowledge\n\n" + "\n".join(records.values()) + "\n## Active research state\n" + active + "\n## Research deltas\n\n" + delta)
    (tmp_path / "RESEARCH_YIELD.md").write_text(ry, encoding="utf-8")
    (tmp_path / "EXPERIMENT_LOG.md").write_text(log, encoding="utf-8")
    (tmp_path / "DECISIONS.md").write_text(decisions, encoding="utf-8")
    (tmp_path / "PROJECT_TRACKING.md").write_text(tracking, encoding="utf-8")
    (tmp_path / "benchmark" / "gates").mkdir(parents=True, exist_ok=True)
    for gate in gates:
        (tmp_path / "benchmark" / "gates" / gate).write_text("gate", encoding="utf-8")
    return v.validate(tmp_path)


def rules(errors):
    return {e.split(" ")[0] for e in errors}


def test_valid_fixture_passes(tmp_path):
    assert build(tmp_path) == []


def test_real_research_documents_pass():
    assert v.validate(ROOT) == []


def test_r1_completed_experiment_without_closure(tmp_path):
    rows = dict(ROWS, **{"EXP-02": ROWS["EXP-02"].replace("| closed | H-001, CAP-001 | alpha not promoted |", "| open | H-001, CAP-001 | alpha not promoted |")})
    assert "R1" in rules(build(tmp_path / "a", rows=rows))
    assert "R1" in rules(build(tmp_path / "b", delta=DELTA.replace("- ELIMINATED WORK: e\n", "")))
    assert "R1" in rules(build(tmp_path / "c", log=LOG + "### gamma_v1 — gate verdict (frozen scorer, unmodified)\n"))


def test_r2_supported_knowledge_without_evidence(tmp_path):
    records = dict(RECORDS, **{"CAP-001": record("CAP-001", "SUPPORTED", "none")})
    assert "R2" in rules(build(tmp_path / "a", records=records))
    records = dict(RECORDS, **{"CAP-001": record("CAP-001", "SUPPORTED", "EXP-99")})
    assert "R2" in rules(build(tmp_path / "b", records=records))


def test_r3_decision_referring_to_missing_or_contradicted_evidence(tmp_path):
    assert "R3" in rules(build(tmp_path / "a", decisions=DECISIONS.replace("CAP-001, H-001(refuted)", "CAP-009")))
    assert "R3" in rules(build(tmp_path / "b", decisions=DECISIONS.replace("H-001(refuted)", "H-001")))
    assert "R3" in rules(build(tmp_path / "c", decisions=DECISIONS.replace("CAP-001, H-001(refuted)", "CAP-001(refuted)")))
    active_without_ids = DECISIONS.replace("| Beta | `beta` | **passed** | cap | passed | beta_v1 | Q-001 |", "| Beta | `beta` | **on** | cap | passed | beta_v1 | — |")
    assert "R3" in rules(build(tmp_path / "d", decisions=active_without_ids))


def test_findings_must_anchor_to_log_headings(tmp_path):
    assert "R2" in rules(build(tmp_path, findings="| FND-01 | Finding: nonexistent | confound | c |"))


def test_r4_confounded_result_without_qualification(tmp_path):
    records = dict(RECORDS, **{"CON-001": record("CON-001", "SUPPORTED", "EXP-01")})
    assert "R4" in rules(build(tmp_path, records=records))


def test_r5_superseded_hypothesis_shown_active(tmp_path):
    records = dict(RECORDS, **{"H-002": record("H-002", "SUPERSEDED", "EXP-03", "- superseded_by: H-001\n")})
    assert "R5" in rules(build(tmp_path / "a", records=records))
    records = dict(RECORDS, **{"H-002": record("H-002", "SUPERSEDED", "EXP-03")})
    assert "R5" in rules(build(tmp_path / "b", records=records, active="- open_questions: Q-001\n"))


def test_r6_next_experiment_registered_before_prior_closure(tmp_path):
    rows = dict(ROWS, **{"EXP-02": ROWS["EXP-02"].replace("| FAIL | frozen_gate", "| PENDING | frozen_gate").replace("| closed |", "| open |")})
    assert "R6" in rules(build(tmp_path, rows=rows))


def test_r7_pending_decision_contradicted_by_later_registration(tmp_path):
    decisions = DECISIONS.replace("- **After beta_v1 (PASS):** pending replication (Q-001).", "- **After alpha_v1 (FAIL):** no next gate registered.")
    assert "R7" in rules(build(tmp_path / "a", decisions=decisions))
    tracking = TRACKING.replace("COMPLETED GATE: alpha_v1", "LAST COMPLETED GATE: alpha_v1")
    assert "R7" in rules(build(tmp_path / "b", tracking=tracking))
    assert "R7" in rules(build(tmp_path / "c", tracking=TRACKING + "ACTIVE GATE: beta_v1 running\n"))


def test_r8_retest_of_closed_hypothesis_without_changed_condition(tmp_path):
    rows = dict(ROWS)
    rows["EXP-04"] = "| EXP-04 | beta_v1 — gate verdict | beta_v1.md | dev | FAIL | frozen_gate | none | H-001 | - | no | closed | H-001 | none | yes | yes |"
    delta = DELTA + AUDIT + (DELTA + AUDIT).replace("EXP-03", "EXP-04")
    errors = build(tmp_path / "a", rows=rows, delta=delta)
    assert "R8" in rules(errors)
    rows["EXP-04"] = rows["EXP-04"].replace("| H-001 | - |", "| H-001 | new model version |")
    assert "R8" not in rules(build(tmp_path / "b", rows=rows, delta=delta))


def test_r9_completed_without_valid_verdict(tmp_path):
    rows = dict(ROWS, **{"EXP-02": ROWS["EXP-02"].replace("| FAIL |", "| DONE |")})
    assert "R9" in rules(build(tmp_path / "a", rows=rows))
    rows = dict(ROWS, **{"EXP-01": ROWS["EXP-01"].replace("| INCONCLUSIVE | no_gate", "| PASS | no_gate")})
    assert "R9" in rules(build(tmp_path / "b", rows=rows))
    assert "R9" in rules(build(tmp_path / "c", gates=("alpha_v1.md", "beta_v1.md", "gamma_v1.md")))


def test_r10_research_question_without_traceable_evidence(tmp_path):
    records = dict(RECORDS, **{"Q-001": record("Q-001", "OPEN", "EXP-03")})
    assert "R10" in rules(build(tmp_path / "a", records=records))
    assert "R10" in rules(build(tmp_path / "b", tracking=TRACKING.replace("pending Q-001.", "pending replication.")))


def test_confidence_levels_required_and_heldout_needs_heldout_evidence(tmp_path):
    records = dict(RECORDS, **{"CAP-001": record("CAP-001", "SUPPORTED", confidence="generally-established")})
    assert "R2" in rules(build(tmp_path / "a", records=records))
    records = dict(RECORDS, **{"CAP-001": record("CAP-001", "SUPPORTED", confidence="heldout-supported")})
    assert "R2" in rules(build(tmp_path / "b", records=records))
    rows = dict(ROWS, **{"EXP-02": ROWS["EXP-02"].replace("| dev | FAIL |", "| heldout | FAIL |")})
    assert "R2" not in rules(build(tmp_path / "c", rows=rows, records=records))


def test_semantic_audit_required_once_protocol_started(tmp_path):
    assert "R1" in rules(build(tmp_path / "a", delta=DELTA + AUDIT.replace("- CAUSAL LANGUAGE: ok\n", "")))
    rows = dict(ROWS)
    rows["EXP-04"] = "| EXP-04 | beta_v1 — gate verdict | beta_v1.md | dev | FAIL | frozen_gate | none | - | - | no | closed | H-002 | none | yes | no |"
    assert "R1" in rules(build(tmp_path / "b", rows=rows, delta=DELTA + AUDIT + DELTA.replace("EXP-03", "EXP-04")))


def test_partial_verdict_only_for_frozen_gates(tmp_path):
    rows = dict(ROWS, **{"EXP-03": ROWS["EXP-03"].replace("| PASS |", "| PARTIAL |")})
    assert build(tmp_path / "a", rows=rows) == []
    rows = dict(ROWS, **{"EXP-01": ROWS["EXP-01"].replace("| INCONCLUSIVE | no_gate", "| PARTIAL | stated_criterion")})
    assert "R9" in rules(build(tmp_path / "b", rows=rows))


def test_active_gate_parses_the_named_gate_and_open_experiments_may_be_active(tmp_path):
    rows = dict(ROWS)
    rows["EXP-04"] = "| EXP-04 | beta_v1 — gate verdict | gamma_v1.md | heldout | PENDING | frozen_gate | none | H-002 | heldout replication | no | open | Q-001 (pending) | pending | yes | yes |"
    tracking = TRACKING.replace("NEXT GATE: none registered; pending Q-001.", "ACTIVE GATE: gamma_v1 (replicates the frozen beta_v1 stack)\nNEXT GATE: after closure, Q-001.")
    errors = build(tmp_path / "a", rows=rows, tracking=tracking, gates=("alpha_v1.md", "beta_v1.md", "gamma_v1.md"),
                   active="- open_hypotheses: H-002\n- open_questions: Q-001\n- active_experiment: EXP-04\n")
    assert errors == []
    tracking_closed = tracking.replace("ACTIVE GATE: gamma_v1", "ACTIVE GATE: beta_v1")
    assert "R7" in rules(build(tmp_path / "b", rows=rows, tracking=tracking_closed, gates=("alpha_v1.md", "beta_v1.md", "gamma_v1.md"),
                               active="- open_questions: Q-001\n- active_experiment: EXP-04\n"))
    assert "R5" in rules(build(tmp_path / "c", active="- open_questions: Q-001\n- active_experiment: EXP-03\n"))