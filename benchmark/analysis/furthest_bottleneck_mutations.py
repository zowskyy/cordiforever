"""Reproducible mutation checks for the Furthest-Reached Bottleneck Taxonomy classifier.

Each mutation replaces one exact anchor in `benchmark/analysis/furthest_bottleneck.py` in memory (the file on disk is
never modified) and runs `tests/test_furthest_bottleneck.py` against the mutated module. Expected status:
  caught      the synthetic suite must fail
  equivalent  the suite is expected to pass; `proven_by` names a caught mutation demonstrating the protected property

Usage (manual; ~3 s per mutation, not part of the default CI run):
  python benchmark/analysis/furthest_bottleneck_mutations.py            # run all, exit 1 on any expectation violation
  python benchmark/analysis/furthest_bottleneck_mutations.py --only NAME
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "benchmark" / "analysis" / "furthest_bottleneck.py"
SUITE = "tests/test_furthest_bottleneck.py"
MODULE = "benchmark.analysis.furthest_bottleneck"

MUTATIONS: list[dict[str, str]] = [
    # --- approved classifier mutations
    {"name": "stage_order_swapped", "expected": "caught",
     "old": "    if r9 is T:\n", "new": "    if r7 is T:\n        return result(\"F3\", \"relevant_selector_never_resolved\")\n    if r9 is T:\n"},
    {"name": "f0_without_blocking_condition", "expected": "caught",
     "old": "    r7, r8, r9, r10 = reach[\"R7\"], reach[\"R8\"], reach[\"R9\"], reach[\"R10\"]\n",
     "new": "    r7, r8, r9, r10 = reach[\"R7\"], reach[\"R8\"], reach[\"R9\"], reach[\"R10\"]\n    if facts.evidence is F:\n        return result(\"F0\", \"evidence_not_acquired\")\n"},
    {"name": "wrong_target_counted_as_f6", "expected": "caught",
     "old": "        parts = [self.relevant, self.resolves, self.valid, self.accepted][: stage - 6]",
     "new": "        parts = [T, self.resolves, self.valid, self.accepted][: stage - 6]"},
    {"name": "f7_without_positive_evidence", "expected": "caught",
     "old": "            if facts.regression_evidence is T:", "new": "            if True:"},
    {"name": "unknown_correctness_counted_as_f6", "expected": "caught",
     "old": "        if any_correct is U:\n            return result(\"UNDETERMINED\", \"accepted_state_correctness_unknown\")\n", "new": ""},
    {"name": "guard_judgement_changes_label", "expected": "caught",
     "old": "        return result(\"F5\", guards[-1][0] if guards else None, guard=guards)",
     "new": "        return result(\"F6\" if guards and guards[-1][1] == GUARD_A else \"F5\", guards[-1][0] if guards else None, guard=guards)"},
    {"name": "undetermined_collapsed_into_f8", "expected": "caught",
     "old": "                return result(\"UNDETERMINED\", \"final_state_correctness_unknown\")",
     "new": "                return result(\"F8\", \"final_state_correctness_unknown\")"},
    {"name": "json_prefix_only_relevance", "expected": "caught",
     "old": "        if t == c or (len(t) > len(c) and t[: len(c)] == c) or (len(c) == len(t) + 1 and c[: len(t)] == t):",
     "new": "        if t == c or (len(t) > len(c) and t[: len(c)] == c) or c[: len(t)] == t:"},
    {"name": "d11_skips_non_edit_mutations", "expected": "caught",
     "old": "            else:\n                files[path] = outcome\n", "new": "            else:\n                pass\n"},
    {"name": "f6_subtype_forced_single", "expected": "caught",
     "old": "    if len(union) > 1:\n        return \"MULTIPLE\"", "new": "    if len(union) > 1:\n        return sorted(union)[0]"},
    # --- UNKNOWN is not FALSE
    {"name": "tri_falsiness_as_false", "expected": "caught",
     "old": "    if value is False:\n        return F", "new": "    if not value:\n        return F"},
    {"name": "tri_any_unknown_as_false", "expected": "caught", "old": "    return U if seen_unknown else F", "new": "    return F"},
    {"name": "oracle_error_as_false", "expected": "caught",
     "old": "            value = (U, f\"oracle error: {exc}\")", "new": "            value = (F, f\"oracle error: {exc}\")"},
    {"name": "oracle_timeout_as_false", "expected": "caught",
     "old": "            if \"oracle timed out\" in detail:\n                value = (U, detail)", "new": "            if \"oracle timed out\" in detail:\n                value = (F, detail)"},
    {"name": "malformed_read_view_ignored", "expected": "caught", "old": "        elif malformed:\n", "new": "        elif False and malformed:\n"},
    {"name": "missing_success_known_state", "expected": "caught",
     "old": "        if success is U:\n            state_known = False", "new": "        if False:\n            state_known = False"},
    {"name": "unclassifiable_as_valid", "expected": "equivalent", "proven_by": "unclassifiable_as_resolved_and_valid",
     "reason": "UNCLASSIFIABLE also makes D8 UNKNOWN, so every proposal chain containing it stays UNKNOWN",
     "old": "                valid = T if terminal == fmt.VALID else U if terminal == fmt.UNCLASSIFIABLE else F",
     "new": "                valid = T if terminal in (fmt.VALID, fmt.UNCLASSIFIABLE) else F"},
    {"name": "unclassifiable_as_resolved_and_valid", "expected": "caught",
     "old": "                resolves = F if terminal == fmt.SELECTOR_FAILURE else U if terminal == fmt.UNCLASSIFIABLE else T\n"
            "                valid = T if terminal == fmt.VALID else U if terminal == fmt.UNCLASSIFIABLE else F",
     "new": "                resolves = F if terminal == fmt.SELECTOR_FAILURE else T\n                valid = T if terminal in (fmt.VALID, fmt.UNCLASSIFIABLE) else F"},
    {"name": "diagnosis_without_path_skipped", "expected": "caught",
     "old": "            if not isinstance(d, dict) or \"path\" not in d:\n                usable_values.append(U)\n                localized_values.append(U)\n                continue",
     "new": "            if not isinstance(d, dict) or \"path\" not in d:\n                continue"},
    {"name": "snapshot_mismatch_as_miss", "expected": "caught",
     "old": "            if u is U or d.get(\"snapshot_matches_seed\") is False or \"hits_defect\" not in d:",
     "new": "            if u is U or \"hits_defect\" not in d:"},
    {"name": "records_mismatch_ignored", "expected": "caught",
     "old": "    state_known = not records_mismatch and all(isinstance(c, dict) for c in calls)",
     "new": "    state_known = all(isinstance(c, dict) for c in calls)"},
    # --- D0 / applicability amendments
    {"name": "d0_harness_uses_contract_as_label", "expected": "caught",
     "old": "    facts.d0_harness, facts.d0_contract, _ = d0_task(", "new": "    facts.d0_contract, facts.d0_harness, _ = d0_task("},
    {"name": "exact_reference_patch_required", "expected": "caught",
     "old": "        classes.append(\"remove_selectable_name\")\n        harness, contract = tri_and(harness, U), tri_and(contract, U)",
     "new": "        classes.append(\"remove_selectable_name\")\n        harness, contract = tri_and(harness, F), tri_and(contract, F)"},
    {"name": "unknown_structural_necessity_as_false", "expected": "caught",
     "old": "                elif _selectable(node):\n                    classes.append(\"modify_selectable\")\n                else:\n"
            "                    classes.append(\"modify_non_selectable\")\n                    verdict = F if (sole_gold and not any_selectable) else U",
     "new": "                elif _selectable(node):\n                    classes.append(\"modify_selectable\")\n                else:\n"
            "                    classes.append(\"modify_non_selectable\")\n                    verdict = F"},
    {"name": "reference_added_intent_ignored", "expected": "caught",
     "old": "            relevant_py[g] = (existing | added) or None", "new": "            relevant_py[g] = existing or None"},
    {"name": "d0_contract_changes_label", "expected": "caught",
     "old": "        return result(\"UNDETERMINED\", \"action_space_applicability_unknown\")\n",
     "new": "        return result(\"UNDETERMINED\", \"action_space_applicability_unknown\")\n    if facts.d0_contract is F:\n        return result(\"INTERFACE_UNSUPPORTED\", \"contract\")\n"},
    {"name": "harness_insertion_marked_unsupported", "expected": "caught",
     "old": "                contract = tri_and(contract, F)  # the single-definition contract cannot add a new top-level statement",
     "new": "                harness, contract = tri_and(harness, F), tri_and(contract, F)"},
    {"name": "d0_unknown_treated_as_supported", "expected": "caught",
     "old": "    if facts.d0_harness is U:\n        return result(\"UNDETERMINED\", \"action_space_applicability_unknown\")\n", "new": ""},
    {"name": "json_root_parent_treated_as_selectable", "expected": "caught",
     "old": "            if candidate == ():\n                continue", "new": "            if candidate == ():\n                ok = True\n                break"},
    {"name": "f1_attempt_sub_labels_collapsed", "expected": "caught",
     "old": "        sub = {T: \"diagnosis_attempted_unusable\", F: \"no_diagnosis_attempted\"}.get(facts.diagnosis_attempted, \"diagnosis_attempt_unknown\")",
     "new": "        sub = \"diagnosis_attempted_unusable\""},
]


def mutated_source(mutation: dict[str, str], source: str | None = None) -> str:
    text = SOURCE.read_text(encoding="utf-8") if source is None else source
    count = text.count(mutation["old"])
    if count != 1:
        raise ValueError(f"{mutation['name']}: anchor occurs {count} times")
    return text.replace(mutation["old"], mutation["new"])


def load_mutated_module(mutation: dict[str, str]):
    """Register the mutated classifier under its real module name. The namespace-package parent must be imported first,
    and the child must be set as an attribute of the parent, or `import benchmark.analysis.furthest_bottleneck` fails."""
    sys.path.insert(0, str(ROOT))
    import benchmark.analysis  # noqa: F401

    spec = importlib.util.spec_from_loader(MODULE, loader=None, origin=str(SOURCE))
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(SOURCE)
    sys.modules[MODULE] = module
    exec(compile(mutated_source(mutation), str(SOURCE), "exec"), module.__dict__)
    sys.modules["benchmark.analysis"].furthest_bottleneck = module
    return module


def _child(name: str) -> int:
    import pytest

    mutation = next(m for m in MUTATIONS if m["name"] == name)
    load_mutated_module(mutation)
    basetemp = Path(os.environ.get("TEMP", "/tmp")) / f"fb_mutation_{name}"
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-W", "ignore", "--basetemp", str(basetemp), SUITE]))


def run(only: str | None = None) -> int:
    violations = 0
    for mutation in MUTATIONS:
        if only and mutation["name"] != only:
            continue
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mutation["name"]], cwd=ROOT,
                              capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if proc.returncode == 1:
            observed = "caught"
        elif proc.returncode == 0:
            observed = "equivalent"
        else:
            observed = f"harness_error(exit {proc.returncode})"
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
