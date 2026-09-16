"""Reproducible mutation checks for the D3-v2 amendment (benchmark/analysis/furthest_bottleneck_taxonomy_v2.md).

Each mutation replaces one exact anchor in `benchmark/analysis/furthest_bottleneck_v2.py` in memory (the file on disk
is never modified; v1 is never touched) and runs `tests/test_furthest_bottleneck_v2.py` against the mutated module.
Expected status:
  caught      the synthetic suite must fail
  equivalent  the suite is expected to pass; `proven_by` names a caught mutation demonstrating the protected property

Usage (manual; not part of the default CI run):
  python benchmark/analysis/furthest_bottleneck_v2_mutations.py
  python benchmark/analysis/furthest_bottleneck_v2_mutations.py --only NAME
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "benchmark" / "analysis" / "furthest_bottleneck_v2.py"
SUITE = "tests/test_furthest_bottleneck_v2.py"
MODULE = "benchmark.analysis.furthest_bottleneck_v2"

_A4_BLOCK = """        out.append((c, call_admission(c, aligned)))
    rejections = row.get("guard_rejections") or []
    for i, (call, admitted) in enumerate(out):
        if call.get("tool") != "edit_symbol" or admitted is not U:
            continue
        p = normalize(str((call.get("args") or {}).get("path") or ""))
        seen = sum(1 for g in rejections if isinstance(g, dict) and g.get("tool") == "edit_symbol"
                   and normalize(str(g.get("path") or "")) == p)
        failed = sum(1 for c2, _a2 in out if c2.get("tool") == "edit_symbol" and c2.get("success") is not True
                     and normalize(str((c2.get("args") or {}).get("path") or "")) == p)
        out[i] = (call, F if seen and seen == failed else T if seen == 0 else U)
    return out
"""

MUTATIONS: list[dict[str, str]] = [
    # --- the cutoff itself
    {"name": "cutoff_reverts_to_first_attempt", "expected": "caught",
     "old": "        if admitted is F:\n            continue  # refused: the system permitted nothing, so it sets no cutoff\n",
     "new": ""},
    {"name": "cutoff_requires_success_d3c", "expected": "caught",
     "old": "        if admitted is F:\n            continue  # refused: the system permitted nothing, so it sets no cutoff\n",
     "new": "        if admitted is not T:\n            continue\n"},
    {"name": "refused_diagnosis_treated_as_admitted", "expected": "caught",
     "old": "        return F if diagnose_admission is F else U  # P2 / P3",
     "new": "        return T if diagnose_admission is F else U  # P2 / P3"},
    {"name": "d3_evaluated_only_at_lmin", "expected": "caught",
     "old": "    return at_min if at_min is at_max else U", "new": "    return at_min"},
    {"name": "d3_evaluated_only_at_lmax", "expected": "equivalent", "proven_by": "d3_evaluated_only_at_lmin",
     "reason": "Requires BOTH: (a) the load-bearing precondition Lmin <= Lmax, which holds on structurally valid "
               "methodology inputs (D3_CALL_POSITION_CONTRACT: every relevant call is positioned and the relevant-call "
               "rounds are non-decreasing in recorded order, so the first non-refused call is at or before the first "
               "admitted one) and on every fixture the suite feeds this helper; and (b) V monotone in the cutoff. "
               "Given (a)+(b), V(Lmax) is TRUE whenever V(Lmin) is, so the shortcut is redundant. Monotonicity alone "
               "is NOT sufficient: on an off-domain row with Lmin > Lmax the shortcut is observable "
               "(e.g. calls=[diag r5 failed, diag r1 admitted], complete view at r3: bounds (5, 1), current code "
               "returns TRUE via the shortcut, the mutant returns UNKNOWN)",
     "old": "    if at_min is T:\n        return T  # V is monotone in the cutoff, and the true cutoff is at least Lmin\n",
     "new": ""},
    {"name": "no_attempt_cutoff_defaults_to_zero", "expected": "caught",
     "old": "    low: float = UNPOSITIONED if malformed_entry else (UNBOUNDED if lmin is None else lmin)",
     "new": "    low: float = UNPOSITIONED if malformed_entry else (0 if lmin is None else lmin)"},
    {"name": "cutoff_uses_smallest_round_not_recorded_order", "expected": "caught",   # M-ORDER
     "old": "        if lmin is None:\n            lmin = rnd\n        if admitted is T and lmax is None:\n            lmax = rnd\n",
     "new": "        lmin = rnd if lmin is None else min(lmin, rnd)\n        if admitted is T:\n            lmax = rnd if lmax is None else min(lmax, rnd)\n"},
    # --- edit_symbol admission must not be inferred
    {"name": "failed_edit_treated_as_admitted", "expected": "caught",
     "old": "    return U                          # P3: no persisted field establishes edit_symbol admission",
     "new": "    return T                          # P3: no persisted field establishes edit_symbol admission"},
    {"name": "failed_edit_treated_as_refused", "expected": "caught",
     "old": "    return U                          # P3: no persisted field establishes edit_symbol admission",
     "new": "    return F                          # P3: no persisted field establishes edit_symbol admission"},
    {"name": "a4_count_pairing_reintroduced", "expected": "caught",
     "old": "        out.append((c, call_admission(c, aligned)))\n    return out\n", "new": _A4_BLOCK},
    # --- diagnose stream preconditions
    {"name": "stream_length_precondition_dropped", "expected": "caught",
     "old": "    if len(diagnose_calls) != len(diagnoses):\n        return None\n", "new": ""},
    {"name": "stream_path_precondition_dropped", "expected": "caught",
     "old": "    for c, record in zip(diagnose_calls, diagnoses):\n"
            "        if normalize(str((c.get(\"args\") or {}).get(\"path\") or \"\")) != normalize(str(record.get(\"path\") or \"\")):\n"
            "            return None\n", "new": ""},
    {"name": "guard_count_consistency_dropped", "expected": "caught",
     "old": "    if sum(1 for g in rejections if g.get(\"tool\") == \"diagnose\") != len(refused_records):\n        return None\n",
     "new": ""},
    {"name": "unrefused_record_treated_as_admitted", "expected": "caught",
     "old": "    return [F if d[\"refused\"] else U for d in diagnoses]",
     "new": "    return [F if d[\"refused\"] else T for d in diagnoses]"},
    {"name": "malformed_refused_field_accepted", "expected": "caught",
     "old": "        if not (record[\"refused\"] is None or isinstance(record[\"refused\"], str)):\n            return None\n",
     "new": ""},
    # --- round counters and malformed evidence
    {"name": "guard_round_compared_with_call_round", "expected": "caught",
     "old": "    for call, admitted in attempt_admissions(row, normalize):\n",
     "new": "    for g in (row.get(\"guard_rejections\") or []):\n"
            "        if isinstance(g, dict) and normalize(str(g.get(\"path\") or \"\")) == path and isinstance(g.get(\"round\"), int):\n"
            "            lmin = min(lmin, g[\"round\"])\n"
            "    for call, admitted in attempt_admissions(row, normalize):\n"},
    {"name": "malformed_call_entry_ignored", "expected": "caught",
     "old": "    malformed_entry = not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)",
     "new": "    malformed_entry = not isinstance(calls, list)"},
    {"name": "non_integer_round_attempt_ignored", "expected": "caught",
     "old": "            malformed_entry = True\n            if admitted is T:", "new": "            if admitted is T:"},
    {"name": "bool_round_treated_as_integer", "expected": "caught",
     "old": "    return value if type(value) is int else None", "new": "    return value if isinstance(value, int) else None"},
    # --- Layer 0: D3_PRODUCER_ENVELOPE_CONTRACT and validation precedence
    {"name": "envelope_validation_removed", "expected": "caught",
     "old": "    check_producer_envelope(row)                    # Layer 0, before anything inspects a call entry\n", "new": ""},
    {"name": "envelope_validation_moved_after_v1", "expected": "caught",
     "old": "    check_producer_envelope(row)                    # Layer 0, before anything inspects a call entry\n"
            "    check_call_positions(row, scope, normalize)     # Layer 1\n",
     "new": "    check_call_positions(row, scope, normalize)\n"
            "    v1.extract_facts(row, task, replayer, defect_lines, repos_dir, normalize, capabilities)\n"
            "    check_producer_envelope(row)\n"},
    {"name": "envelope_validation_moved_after_position", "expected": "caught",   # swaps Layer 0 / Layer 1 order
     "old": "    check_producer_envelope(row)                    # Layer 0, before anything inspects a call entry\n"
            "    check_call_positions(row, scope, normalize)     # Layer 1\n",
     "new": "    check_call_positions(row, scope, normalize)\n    check_producer_envelope(row)\n"},
    {"name": "envelope_accepts_non_list_calls", "expected": "caught",
     "old": "    if not isinstance(calls, list):\n        return [f\"`calls` is {type(calls).__name__}, not a list\"]\n", "new": ""},
    {"name": "envelope_accepts_missing_calls", "expected": "equivalent", "proven_by": "envelope_accepts_non_list_calls",
     "reason": "Removing the explicit missing-key branch changes only the message: row.get('calls') is then None, "
               "which the very next check rejects as not-a-list, so the row is still refused with "
               "RowEnvelopeViolation and nothing observable to the methodology changes. "
               "envelope_accepts_non_list_calls proves that surviving check is load-bearing.",
     "old": "    if \"calls\" not in row:\n        return [\"row has no `calls`\"]\n", "new": ""},
    {"name": "envelope_accepts_non_dict_entry", "expected": "caught",
     "old": "        if not isinstance(call, dict):\n            violations.append(f\"calls[{index}] is {type(call).__name__}, not a dict\")\n            continue\n",
     "new": "        if not isinstance(call, dict):\n            continue\n"},
    {"name": "envelope_accepts_non_dict_args", "expected": "caught",
     "old": "        if args is not None and not isinstance(args, dict):\n", "new": "        if False:\n"},
    {"name": "envelope_rejects_absent_or_none_args", "expected": "caught",       # over-rejection breaks minimality
     "old": "        if args is not None and not isinstance(args, dict):\n", "new": "        if not isinstance(args, dict):\n"},
    {"name": "envelope_accepts_falsy_non_dict_args", "expected": "caught",       # loosening: the documented boundary
     "old": "        if args is not None and not isinstance(args, dict):\n", "new": "        if args and not isinstance(args, dict):\n"},
    {"name": "extract_facts_v2_alters_a_non_evidence_field", "expected": "caught",
     "old": "    return replace(facts, evidence=d3_v2(row, scope, normalize)), descriptive_facts(row, scope, normalize)",
     "new": "    return replace(facts, evidence=d3_v2(row, scope, normalize), localized=U), descriptive_facts(row, scope, normalize)"},
    {"name": "descriptive_malformed_predicate_drifts", "expected": "caught",
     "old": "    malformed_calls = not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)",
     "new": "    malformed_calls = not isinstance(calls, list)"},
    # --- UNPOSITIONED sentinel: epistemic uncertainty must never become a determined value
    {"name": "malformed_calls_default_to_unbounded", "expected": "caught",
     "old": "    malformed_entry = not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)",
     "new": "    malformed_entry = isinstance(calls, list) and any(not isinstance(c, dict) for c in calls)"},
    {"name": "duplicate_d3_v2_guard_masks_cutoff_regression", "expected": "caught",
     "old": "    malformed_entry = not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)",
     "new": "    malformed_entry = False\n    if not isinstance(calls, list):\n        return (UNPOSITIONED, UNBOUNDED)"},
    {"name": "unpositioned_lower_bound_evaluated_as_a_cutoff", "expected": "caught",
     "old": "    if lmin == UNPOSITIONED:\n", "new": "    if False:\n"},
    {"name": "unpositioned_rule_returns_false", "expected": "caught",
     "old": "        return U\n    views = row.get(\"read_views\")", "new": "        return F\n    views = row.get(\"read_views\")"},
    {"name": "unpositioned_sentinel_is_a_real_cutoff", "expected": "caught",
     "old": "UNPOSITIONED = float(\"-inf\")", "new": "UNPOSITIONED = 0"},
    # --- D3 gold-file domain must equal v1's exactly
    {"name": "domain_requires_non_empty_python_region", "expected": "caught",
     "old": "        if g.endswith(\".py\") or g.endswith(\".json\"):\n            scope.append(g)\n",
     "new": "        if g.endswith(\".json\"):\n            scope.append(g)\n        elif g.endswith(\".py\"):\n"
            "            seed = (repos_dir / task.repo / g).read_text(encoding=\"utf-8\")\n"
            "            region = v1.widened_defect_region(seed, reference[g], defect_lines)\n"
            "            if v1.relevant_python_symbols(seed, region) or v1.reference_added_python_names(seed, reference[g]):\n"
            "                scope.append(g)\n"},
    {"name": "domain_requires_non_empty_json_changes", "expected": "caught",
     "old": "        if g.endswith(\".py\") or g.endswith(\".json\"):\n            scope.append(g)\n",
     "new": "        if g.endswith(\".py\"):\n            scope.append(g)\n        elif g.endswith(\".json\"):\n"
            "            import json as _json\n            try:\n"
            "                changed = v1.json_changed_locations(_json.loads((repos_dir / task.repo / g).read_text(encoding=\"utf-8\")), _json.loads(reference[g]))\n"
            "            except ValueError:\n                changed = []\n"
            "            if changed:\n                scope.append(g)\n"},
    {"name": "domain_drops_json_files", "expected": "caught",
     "old": "        if g.endswith(\".py\") or g.endswith(\".json\"):", "new": "        if g.endswith(\".py\"):"},
    {"name": "domain_includes_any_extension", "expected": "caught",
     "old": "        if g.endswith(\".py\") or g.endswith(\".json\"):\n            scope.append(g)\n",
     "new": "        scope.append(g)\n"},
    {"name": "domain_ignores_missing_seed_file", "expected": "caught",
     "old": "        if not (repos_dir / task.repo / g).is_file() or g not in reference:\n            continue\n",
     "new": "        if g not in reference:\n            continue\n"},
    {"name": "domain_ignores_the_reference_patch", "expected": "caught",
     "old": "        if not (repos_dir / task.repo / g).is_file() or g not in reference:\n            continue\n",
     "new": "        if not (repos_dir / task.repo / g).is_file():\n            continue\n"},
    {"name": "domain_drops_path_normalization", "expected": "caught",
     "old": "    for g in [normalize(g) for g in task.gold_files]:", "new": "    for g in list(task.gold_files):"},
    {"name": "empty_domain_returns_tri_and_of_nothing", "expected": "caught",
     "old": "    if not scope:\n        return U\n", "new": ""},
    # --- input validity: D3_CALL_POSITION_CONTRACT
    {"name": "validity_check_removed", "expected": "caught",
     "old": "    check_call_positions(row, scope, normalize)     # Layer 1\n", "new": ""},
    {"name": "validity_violation_swallowed", "expected": "caught",
     "old": "    check_call_positions(row, scope, normalize)     # Layer 1\n",
     "new": "    try:\n        check_call_positions(row, scope, normalize)\n    except RowContractViolation:\n        pass\n"},
    {"name": "validity_violation_becomes_unknown", "expected": "caught",
     "old": "    if violations:\n        raise RowContractViolation(\"; \".join(violations))", "new": "    return None"},
    {"name": "validity_checked_after_extraction", "expected": "caught",
     "old": "    check_call_positions(row, scope, normalize)     # Layer 1\n"
            "    # Only now is frozen v1 provably safe to call: it dereferences every call entry unguarded at\n"
            "    # furthest_bottleneck.py:858-859, so an envelope violation would surface there as an AttributeError.\n"
            "    facts = v1.extract_facts(row, task, replayer, defect_lines, repos_dir, normalize, capabilities)\n",
     "new": "    facts = v1.extract_facts(row, task, replayer, defect_lines, repos_dir, normalize, capabilities)\n"
            "    check_call_positions(row, scope, normalize)\n"},
    {"name": "missing_relevant_round_accepted", "expected": "caught",
     "old": "        if \"round\" not in call:\n            violations.append(f\"calls[{index}] {call.get('tool')} on {path} has no round\")\n            continue\n",
     "new": "        if \"round\" not in call:\n            continue\n"},
    {"name": "non_integer_relevant_round_accepted", "expected": "caught",
     "old": "        rnd = positioned_round(call)\n        if rnd is None:\n            violations.append(f\"calls[{index}] {call.get('tool')} on {path} has round \"\n"
            "                              f\"{call.get('round')!r} of type {type(call.get('round')).__name__}, not int\")\n            continue\n",
     "new": "        rnd = positioned_round(call)\n        if rnd is None:\n            continue\n"},
    {"name": "unpositioned_admitted_bound_dropped", "expected": "caught",
     "old": "            if admitted is T:\n                unpositioned_admitted = True\n", "new": ""},
    {"name": "p1_accepts_truthiness", "expected": "caught",
     "old": "    if call.get(\"success\") is True:", "new": "    if call.get(\"success\"):"},
    {"name": "strict_increase_required", "expected": "caught",
     "old": "        if after < before:", "new": "        if after <= before:"},
    {"name": "any_round_change_rejected", "expected": "caught",
     "old": "        if after < before:", "new": "        if after != before:"},
    {"name": "round_zero_rejected", "expected": "caught",
     "old": "    return value if type(value) is int else None", "new": "    return value if type(value) is int and value != 0 else None"},
    {"name": "contract_widened_to_all_tools", "expected": "caught",
     "old": "        if not isinstance(call, dict) or call.get(\"tool\") not in ATTEMPT_TOOLS:\n            continue\n",
     "new": "        if not isinstance(call, dict):\n            continue\n"},
    {"name": "contract_ignores_the_gold_file_scope", "expected": "caught",
     "old": "        if normalize(str((call.get(\"args\") or {}).get(\"path\") or \"\")) in scope:\n            out.append((index, call))\n",
     "new": "        out.append((index, call))\n"},
    {"name": "contract_restarted_per_gold_file", "expected": "caught",
     "old": "    for (_i, previous, before), (j, call, after) in zip(positioned, positioned[1:]):\n",
     "new": "    groups: dict[str, list] = {}\n"
            "    for entry in positioned:\n"
            "        groups.setdefault(normalize(str((entry[1].get(\"args\") or {}).get(\"path\") or \"\")), []).append(entry)\n"
            "    for (_i, previous, before), (j, call, after) in "
            "[pair for g in groups.values() for pair in zip(g, g[1:])]:\n"},
    {"name": "view_cutoff_strictly_before", "expected": "caught",
     "old": "and v[\"round\"] <= limit]", "new": "and v[\"round\"] < limit]"},
    {"name": "malformed_view_ignored", "expected": "caught",
     "old": "    if malformed:\n        return U  # an unreadable view record might have been a complete read\n", "new": ""},
    {"name": "attempt_path_normalization_dropped", "expected": "caught",
     "old": "        if normalize(str((call.get(\"args\") or {}).get(\"path\") or \"\")) != path:",
     "new": "        if str((call.get(\"args\") or {}).get(\"path\") or \"\") != path:"},
    {"name": "gold_files_aggregated_with_any", "expected": "caught",
     "old": "    return tri_and(*[d3_file(row, g, normalize) for g in scope])",
     "new": "    return v1.tri_any([d3_file(row, g, normalize) for g in scope])"},
    # --- descriptive facts must stay descriptive
    {"name": "descriptive_fact_feeds_classification", "expected": "caught",
     "old": "    return replace(facts, evidence=d3_v2(row, scope, normalize)), descriptive_facts(row, scope, normalize)",
     "new": "    descriptive = descriptive_facts(row, scope, normalize)\n"
            "    value = F if descriptive[\"D3_OBSERVED_PRE_EVIDENCE_ATTEMPT\"] == \"TRUE\" else d3_v2(row, scope, normalize)\n"
            "    return replace(facts, evidence=value), descriptive"},
    {"name": "pre_evidence_fact_counts_admitted_calls_only", "expected": "caught",
     "old": "    for call, _admitted in attempts:\n", "new": "    for call, _admitted in attempts:\n        if _admitted is F:\n            continue\n"},
    {"name": "no_attempt_reported_as_attempt_observed", "expected": "caught",
     "old": "    observed = U if malformed_calls else (T if attempts else F)", "new": "    observed = U if malformed_calls else T"},
]


class AnchorError(RuntimeError):
    """The mutation's anchor no longer matches the source exactly once — the mutation never ran."""


def mutated_source(mutation: dict[str, str]) -> str:
    source = SOURCE.read_text(encoding="utf-8")
    if source.count(mutation["old"]) != 1:
        raise AnchorError(f"anchor for {mutation['name']} occurs {source.count(mutation['old'])} times; expected exactly 1")
    return source.replace(mutation["old"], mutation["new"])


def load_mutated_module(mutation: dict[str, str]):
    """Import the package parents first: `benchmark.analysis` is a namespace package here, so the child module must be
    registered in sys.modules and set as an attribute of the parent."""
    sys.path.insert(0, str(ROOT))
    import benchmark.analysis  # noqa: F401

    spec = importlib.util.spec_from_loader(MODULE, loader=None, origin=str(SOURCE))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(SOURCE)
    sys.modules[MODULE] = module
    exec(compile(mutated_source(mutation), str(SOURCE), "exec"), module.__dict__)
    sys.modules["benchmark.analysis"].furthest_bottleneck_v2 = module
    return module


STATUS_PREFIX = "FBV2-STATUS:"   # runner-owned channel: the parent never infers status from an exit code alone


def _child(name: str) -> int:
    import pytest

    mutation = next(m for m in MUTATIONS if m["name"] == name)
    try:
        load_mutated_module(mutation)
    except AnchorError as exc:
        # Never report a stale anchor as a kill: it silently masked two mutations once.
        print(f"{STATUS_PREFIX} anchor_error {exc}")
        return 3
    except Exception as exc:  # the mutated source did not even import
        print(f"{STATUS_PREFIX} mutation_load_error {type(exc).__name__}: {exc}")
        return 4
    basetemp = Path(os.environ.get("FB_V2_BASETEMP") or os.environ.get("TEMP", "/tmp")) / f"fb_v2_mutation_{name}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    code = int(pytest.main(["-q", "-p", "no:cacheprovider", "-W", "ignore", "--basetemp", str(basetemp), SUITE]))
    # pytest: 0 all passed, 1 tests failed, 2 interrupted, 3 internal error, 4 usage error, 5 no tests collected.
    status = {0: "survived", 1: "caught"}.get(code, f"pytest_error(exit {code})")
    print(f"{STATUS_PREFIX} {status}")
    return code


def run(only: str | None = None) -> int:
    violations = 0
    for mutation in MUTATIONS:
        if only and mutation["name"] != only:
            continue
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mutation["name"]], cwd=ROOT,
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        reported = next((line[len(STATUS_PREFIX):].strip() for line in proc.stdout.splitlines()
                         if line.startswith(STATUS_PREFIX)), None)
        if reported is None:
            # No status line: the child died before it could report. Never a kill.
            observed = f"child_error(exit {proc.returncode})"
        elif reported == "caught":
            observed = "caught"
        elif reported == "survived":
            observed = "equivalent"
        else:
            # anchor_error, mutation_load_error, pytest_error(...): infrastructure, never a mutation kill
            observed = reported.split()[0]
        summary = next((line for line in reversed(proc.stdout.splitlines()) if " passed" in line or " failed" in line or " error" in line), "")
        ok = observed == mutation["expected"]
        violations += 0 if ok else 1
        print(f"{'OK ' if ok else 'BAD'} {mutation['name']}: expected {mutation['expected']}, observed {observed} ({summary.strip()})")
    print(f"mutations: {'OK' if violations == 0 else f'{violations} violation(s)'}")
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        raise SystemExit(_child(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--only":
        raise SystemExit(run(sys.argv[2]))
    raise SystemExit(run())
