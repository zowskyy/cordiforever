"""D3-v2 amendment to the Furthest-Reached Bottleneck Taxonomy (benchmark/analysis/furthest_bottleneck_taxonomy_v2.md).

Single-factor amendment: D3's cutoff is the first GUARD-ADMITTED evidence-dependent action on a gold file, instead of
v1's first attempted action. Everything else, `classify` included, is v1's and is imported unmodified.

Admission is read only from persisted fields, and only where they establish it:
  P1  success is True                       -> TRUE  (the handler ran)
  P2  diagnose, A5 preconditions hold and the aligned record has a refused reason -> FALSE
  P3  anything else                         -> UNKNOWN
Absence of a guard rejection never means admission; a guard rejection never means non-admission for edit_symbol; the
two round counters are never compared; guard-rejection counts are consistency evidence only. See the specification
section 3 for the harness evidence behind each of those rules.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import benchmark.analysis.furthest_bottleneck as v1
from benchmark.analysis.furthest_bottleneck import F, T, Tri, TrajectoryFacts, U, tri_and

# The evidence-dependent action set is v1's and is not changed by this amendment.
ATTEMPT_TOOLS = ("diagnose", "edit_symbol")
PRODUCER_ENVELOPE_CONTRACT = "D3_PRODUCER_ENVELOPE_CONTRACT"
CALL_POSITION_CONTRACT = "D3_CALL_POSITION_CONTRACT"

# Lower-bound sentinel: "the earliest potentially relevant or admitted downstream action cannot be positioned from the
# available telemetry". It is epistemic uncertainty about the cutoff, NOT a temporal cutoff before all views, and
# `d3_file` maps it straight to UNKNOWN. UNBOUNDED is the ordinary "no such action" upper/lower bound.
UNPOSITIONED = float("-inf")
UNBOUNDED = float("inf")

classify = v1.classify


def positioned_round(call: dict[str, Any]) -> int | None:
    """The persisted round of a call, or None when it is not exactly an int.

    `type(...) is int`, not `isinstance`: `bool` subclasses `int`, and a `True` round must take the conservative
    malformed path rather than act as round 1. The positional counter in `call_log` only ever writes plain ints
    (benchmark/repo_task_eval.py:235-249), so this rejects nothing a producer row contains."""
    value = call.get("round")
    return value if type(value) is int else None


# ============================================================================= input validity (D3_CALL_POSITION_CONTRACT)
class RowContractViolation(ValueError):
    """A row that the evaluator producer could not have emitted. Not a D3 value, not a label, not UNKNOWN: the row is
    outside the methodology domain and is refused rather than classified."""

    def __init__(self, detail: str, contract: str = CALL_POSITION_CONTRACT) -> None:
        super().__init__(f"{contract}: {detail}")
        self.contract = contract
        self.detail = detail


class RowEnvelopeViolation(RowContractViolation):
    """Layer 0: the row is not shaped the way the evaluator producer shapes rows, so its call entries cannot be
    inspected safely at all. A subclass, so existing `except RowContractViolation` handling keeps working while a
    caller that cares can tell the two causes apart."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail, contract=PRODUCER_ENVELOPE_CONTRACT)


def producer_envelope_violations(row: dict[str, Any]) -> list[str]:
    """Every breach of D3_PRODUCER_ENVELOPE_CONTRACT (Layer 0).

    Minimal by construction: a requirement is here only when the producer provably guarantees it AND methodology
    safety depends on it (`call_log`, benchmark/repo_task_eval.py:228-259).
      1. `calls` exists;
      2. `calls` is a list;
      3. every entry is a dict          - frozen v1 raises AttributeError otherwise (furthest_bottleneck.py:859);
      4. a PRESENT, NON-NULL `args` is a dict.

    Requirement 4 in full: `args` absent, `args is None` and `args == {}` are ACCEPTED; every other non-null value -
    `[]`, `""`, `0`, `False`, `"x"`, `7`, `True`, any non-dict - is REJECTED. Falsy non-dicts are rejected even though
    today's `(call.get("args") or {}).get(...)` happens not to raise on them: Layer 0 defines the admitted
    producer-envelope SHAPE, not the set of values that incidentally survive one current accessor. Absent and None are
    deliberate methodology relaxations, because the `or {}` idiom makes them indistinguishable from `{}`; arbitrary
    non-null non-dicts are simply not admitted.

    Requirement 4 is still the METHODOLOGY MINIMUM rather than the producer guarantee: the producer always writes
    `args` and always builds it with a dict comprehension (repo_task_eval.py:247), so absent/None is
    producer-impossible, yet the methodology tolerates it. Nothing else is required here - not `tool`, `success`,
    `result_head`, a string `args["path"]` (the producer legitimately summarizes long strings into a dict,
    repo_task_eval.py:193-196), nor any other field. This is not a general schema validator."""
    if "calls" not in row:
        return ["row has no `calls`"]
    calls = row.get("calls")
    if not isinstance(calls, list):
        return [f"`calls` is {type(calls).__name__}, not a list"]
    violations = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            violations.append(f"calls[{index}] is {type(call).__name__}, not a dict")
            continue
        args = call.get("args")
        if args is not None and not isinstance(args, dict):
            violations.append(f"calls[{index}] has args of type {type(args).__name__}, not a dict")
    return violations


def check_producer_envelope(row: dict[str, Any]) -> None:
    """Raise if the row is outside the producer envelope. Runs before Layer 1 and before frozen v1 extraction."""
    violations = producer_envelope_violations(row)
    if violations:
        raise RowEnvelopeViolation("; ".join(violations))


def _relevant_calls(row: dict[str, Any], scope: list[str],
                    normalize: Callable[[str], str]) -> list[tuple[int, dict[str, Any]]]:
    """(index, call) for every identifiable diagnose/edit_symbol call on a D3 gold file, in recorded `calls` order.

    A non-dict entry is not inspectable enough to decide relevance, so it is neither declared relevant nor declared
    irrelevant and is not a contract violation (structural invalidity needs positive evidence about an *identifiable*
    relevant call). Instead it makes the lower cutoff UNPOSITIONED in `cutoff_bounds`, and `d3_file` maps that
    condition directly to UNKNOWN — the conservative result comes from the decision layer, not from `view_value`."""
    calls = row.get("calls")
    if not isinstance(calls, list):
        return []
    out = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict) or call.get("tool") not in ATTEMPT_TOOLS:
            continue
        if normalize(str((call.get("args") or {}).get("path") or "")) in scope:
            out.append((index, call))
    return out


def call_position_violations(row: dict[str, Any], scope: list[str], normalize: Callable[[str], str]) -> list[str]:
    """Every breach of D3_CALL_POSITION_CONTRACT: an unpositioned relevant call, or a decrease across the
    relevant-call subsequence. Empty list means the row is in the structural methodology domain.

    The subsequence spans the WHOLE gold-file domain and the comparison is never restarted per file: the producer
    invariant is global call ordering."""
    violations: list[str] = []
    positioned: list[tuple[int, dict[str, Any], int]] = []
    for index, call in _relevant_calls(row, scope, normalize):
        path = normalize(str((call.get("args") or {}).get("path") or ""))
        if "round" not in call:
            violations.append(f"calls[{index}] {call.get('tool')} on {path} has no round")
            continue
        rnd = positioned_round(call)
        if rnd is None:
            violations.append(f"calls[{index}] {call.get('tool')} on {path} has round "
                              f"{call.get('round')!r} of type {type(call.get('round')).__name__}, not int")
            continue
        positioned.append((index, call, rnd))
    for (_i, previous, before), (j, call, after) in zip(positioned, positioned[1:]):
        if after < before:
            violations.append(
                f"calls[{j}] {call.get('tool')} on "
                f"{normalize(str((call.get('args') or {}).get('path') or ''))} has round {after}, "
                f"after {previous.get('tool')} at round {before}"
            )
    return violations


def check_call_positions(row: dict[str, Any], scope: list[str], normalize: Callable[[str], str]) -> None:
    """Raise if the row violates D3_CALL_POSITION_CONTRACT. Called before any D3-v2 work."""
    violations = call_position_violations(row, scope, normalize)
    if violations:
        raise RowContractViolation("; ".join(violations))


# ============================================================================= admission
def diagnose_admissions(row: dict[str, Any], normalize: Callable[[str], str]) -> list[Tri] | None:
    """Per-diagnose-call admission from the aligned `diagnoses` stream, or None if the A5 preconditions fail.

    A refused record is positive non-admission only while the stream provably lines up with `calls`: a recovery retry
    of a rejected diagnose emits a second guard.rejected and therefore an extra record for one tool.result, which
    breaks precondition 2 or 4 and degrades the whole stream to UNKNOWN."""
    calls, diagnoses, rejections = row.get("calls"), row.get("diagnoses"), row.get("guard_rejections")
    if not isinstance(calls, list) or not isinstance(diagnoses, list):
        return None
    diagnose_calls = [c for c in calls if isinstance(c, dict) and c.get("tool") == "diagnose"]
    if len(diagnose_calls) != len(diagnoses):
        return None
    if not isinstance(rejections, list) or not all(isinstance(g, dict) for g in rejections):
        return None
    for record in diagnoses:
        if not isinstance(record, dict) or "refused" not in record:
            return None
        if not (record["refused"] is None or isinstance(record["refused"], str)):
            return None
    refused_records = [d for d in diagnoses if d["refused"]]
    if sum(1 for g in rejections if g.get("tool") == "diagnose") != len(refused_records):
        return None
    for c, record in zip(diagnose_calls, diagnoses):
        if normalize(str((c.get("args") or {}).get("path") or "")) != normalize(str(record.get("path") or "")):
            return None
    return [F if d["refused"] else U for d in diagnoses]


def call_admission(call: dict[str, Any], diagnose_admission: Tri) -> Tri:
    """P1/P2/P3 for one attempt call. `diagnose_admission` is the aligned stream value (UNKNOWN when unavailable)."""
    if call.get("success") is True:
        return T                      # P1: reachable only after the handler returned
    if call.get("tool") == "diagnose":
        return F if diagnose_admission is F else U  # P2 / P3
    return U                          # P3: no persisted field establishes edit_symbol admission


def attempt_admissions(row: dict[str, Any], normalize: Callable[[str], str]) -> list[tuple[dict[str, Any], Tri]]:
    """Every attempt call in `calls` order, with its admission value."""
    calls = row.get("calls")
    if not isinstance(calls, list):
        return []
    stream = diagnose_admissions(row, normalize)
    out: list[tuple[dict[str, Any], Tri]] = []
    index = -1
    for c in calls:
        if not isinstance(c, dict):
            continue
        if c.get("tool") == "diagnose":
            index += 1
        if c.get("tool") not in ATTEMPT_TOOLS:
            continue
        aligned = stream[index] if stream is not None and c.get("tool") == "diagnose" and 0 <= index < len(stream) else U
        out.append((c, call_admission(c, aligned)))
    return out


# ============================================================================= cutoff and D3
def view_value(views: Any, path: str, limit: float) -> Tri:
    """v1's per-file view logic at an explicit cutoff (furthest_bottleneck.py:862-881), unchanged."""
    if not isinstance(views, list):
        return U
    malformed = any(not isinstance(v, dict) or "path" not in v or not isinstance(v.get("round"), int) for v in views)
    before = [v for v in views if isinstance(v, dict) and v.get("path") == path and isinstance(v.get("round"), int) and v["round"] <= limit]
    completes = [v.get("complete") for v in before]
    if any(x is True for x in completes):
        return T
    if malformed:
        return U  # an unreadable view record might have been a complete read
    if all(x is False for x in completes):
        return F  # includes: no view of the file at all
    return U


def cutoff_bounds(row: dict[str, Any], path: str, normalize: Callable[[str], str]) -> tuple[float, float]:
    """(Lmin, Lmax): the earliest and latest round the guard-admitted cutoff for `path` can have.

    Ordering is v1's: the FIRST qualifying action in recorded `calls` order, never the smallest numeric round and
    never a sorted view of the calls (furthest_bottleneck.py:857-861 uses `first_round.setdefault`). The amendment
    changes only which actions qualify. Numeric rounds are used solely to compare a read against the chosen cutoff,
    exactly as in v1."""
    calls = row.get("calls")
    lmin: float | None = None
    lmax: float | None = None
    unpositioned_admitted = False
    # Canonical normalization of malformed telemetry, in ONE place: `calls` missing or not a list is exactly as
    # unpositionable as a non-dict entry, and both must reach the decision layer as UNPOSITIONED. Keeping a second
    # guard elsewhere is what let the two drift apart before.
    malformed_entry = not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)
    for call, admitted in attempt_admissions(row, normalize):
        if normalize(str((call.get("args") or {}).get("path") or "")) != path:
            continue
        if admitted is F:
            continue  # refused: the system permitted nothing, so it sets no cutoff
        rnd = positioned_round(call)
        if rnd is None:
            # an attempt at an unknown position could be the earliest admissible cutoff, and if it was admitted the
            # true cutoff could be it rather than any later one
            malformed_entry = True
            if admitted is T:
                unpositioned_admitted = True
            continue
        if lmin is None:
            lmin = rnd
        if admitted is T and lmax is None:
            lmax = rnd
    low: float = UNPOSITIONED if malformed_entry else (UNBOUNDED if lmin is None else lmin)
    high: float = UNBOUNDED if (unpositioned_admitted or lmax is None) else lmax
    return low, high


def d3_file(row: dict[str, Any], path: str, normalize: Callable[[str], str]) -> Tri:
    lmin, lmax = cutoff_bounds(row, path, normalize)
    if lmin == UNPOSITIONED:
        # Epistemic uncertainty, not a temporal cutoff: the earliest potentially relevant or admitted action cannot be
        # positioned from this telemetry, so no pair of view evaluations may manufacture a determined answer. Note
        # V(-inf) is FALSE (no view precedes it), so without this branch an all-FALSE agreement would assert FALSE
        # even with a complete view above Lmax.
        return U
    views = row.get("read_views")
    at_min = view_value(views, path, lmin)
    if at_min is T:
        return T  # V is monotone in the cutoff, and the true cutoff is at least Lmin
    at_max = view_value(views, path, lmax)
    return at_min if at_min is at_max else U


def d3_v2(row: dict[str, Any], scope: list[str], normalize: Callable[[str], str]) -> Tri:
    """D3-v2 over the gold files in scope (v1's D1-region files).

    No malformed-`calls` guard here: `cutoff_bounds` is the single normalization point, and a malformed row reaches
    this function as UNPOSITIONED per file, hence UNKNOWN. A second guard would mask a regression in that path."""
    if not scope:
        return U
    return tri_and(*[d3_file(row, g, normalize) for g in scope])


# ============================================================================= descriptive facts (never classify inputs)
def descriptive_facts(row: dict[str, Any], scope: list[str], normalize: Callable[[str], str]) -> dict[str, str]:
    """D3_ATTEMPT_OBSERVED and D3_OBSERVED_PRE_EVIDENCE_ATTEMPT.

    FALSE for D3_OBSERVED_PRE_EVIDENCE_ATTEMPT means only "no pre-evidence attempt was observed"; it is not by itself
    evidence that the model waited for evidence (that reading needs D3_ATTEMPT_OBSERVED TRUE alongside it)."""
    calls = row.get("calls")
    malformed_calls = not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)
    views = row.get("read_views")
    attempts = [(c, a) for c, a in attempt_admissions(row, normalize)
                if normalize(str((c.get("args") or {}).get("path") or "")) in scope]
    observed = U if malformed_calls else (T if attempts else F)
    values: list[Tri] = []
    for call, _admitted in attempts:
        rnd = positioned_round(call)
        if rnd is None:
            values.append(U)
            continue
        path = normalize(str((call.get("args") or {}).get("path") or ""))
        at_attempt = view_value(views, path, rnd)
        values.append(F if at_attempt is T else T if at_attempt is F else U)
    pre_evidence = U if malformed_calls else v1.tri_any(values) if values else F
    return {"D3_ATTEMPT_OBSERVED": observed.value, "D3_OBSERVED_PRE_EVIDENCE_ATTEMPT": pre_evidence.value}


# ============================================================================= scope and row entry points
def d1_region_files(task: Any, repos_dir: Path, defect_lines: Callable[[str, str], set[int]],
                    normalize: Callable[[str], str]) -> list[str]:
    """Exactly the gold-file domain v1's D3 ranges over (furthest_bottleneck.py:818-866).

    v1 admits a gold file when its `regions` or `changed_json` KEY exists, which happens whenever the seed file is
    present, the file appears in the reference patch, and it is .py or .json. Whether the region is empty, None or
    unparseable does not narrow the domain there (it only makes D1/D2 UNKNOWN), so it must not narrow it here: this
    amendment is not authorized to redefine which files participate in D3. The `defect_lines` parameter is unused and
    kept for signature symmetry with v1's extractor."""
    reference = {normalize(k): v for k, v in (task.reference_patch or {}).items()}
    scope: list[str] = []
    for g in [normalize(g) for g in task.gold_files]:
        if not (repos_dir / task.repo / g).is_file() or g not in reference:
            continue
        if g.endswith(".py") or g.endswith(".json"):
            scope.append(g)
    return scope


def extract_facts_v2(row: dict[str, Any], task: Any, replayer: Any, defect_lines: Callable[[str, str], set[int]],
                     repos_dir: Path, normalize: Callable[[str], str],
                     capabilities: dict[str, bool] | None = None) -> tuple[TrajectoryFacts, dict[str, str]]:
    """v1 facts with D3 replaced by D3-v2, plus the descriptive facts (which never enter `classify`).

    Raises RowContractViolation before any extraction when the row could not have come from the evaluator producer.
    The exception is never caught here: a structurally invalid row must not reach `classify` by any path."""
    scope = d1_region_files(task, repos_dir, defect_lines, normalize)
    check_producer_envelope(row)                    # Layer 0, before anything inspects a call entry
    check_call_positions(row, scope, normalize)     # Layer 1
    # Only now is frozen v1 provably safe to call: it dereferences every call entry unguarded at
    # furthest_bottleneck.py:858-859, so an envelope violation would surface there as an AttributeError.
    facts = v1.extract_facts(row, task, replayer, defect_lines, repos_dir, normalize, capabilities)
    return replace(facts, evidence=d3_v2(row, scope, normalize)), descriptive_facts(row, scope, normalize)


def classify_row_v2(row: dict[str, Any], task: Any, replayer: Any = None) -> tuple[v1.BottleneckResult, dict[str, str]]:
    from benchmark import repo_task_eval as rte
    from core.path_candidates import normalize

    condition = row.get("condition")
    caps = v1.action_capabilities(rte.CONDITIONS.get(condition, {}).get("overrides")) if isinstance(condition, str) and condition in rte.CONDITIONS else None
    facts, descriptive = extract_facts_v2(row, task, replayer or v1.OracleReplayer(), rte.defect_lines, rte.REPOS_DIR, normalize, caps)
    return classify(facts), descriptive
