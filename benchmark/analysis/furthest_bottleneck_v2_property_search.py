"""Deterministic differential/property verifier for the D3-v2 methodology candidate.

VERIFICATION TOOLING, not methodology: this script does not define D3, it checks the candidate's claimed properties
over synthetic rows. It is intended to run on GitHub Actions so the search does not consume laptop RAM.

REAL-DATA FIREWALL, structural: this verifier has NO code path that can load an experimental result row. It takes no
input-path argument, never opens `benchmark/results/`, and constructs every row internally from deterministic
generators. Its only file reads are the seed corpus and task definitions (task INPUT, the same sources the frozen v1
test-suite uses) and a temporary directory it creates itself.

Properties checked over rows valid under BOTH contracts (D3_PRODUCER_ENVELOPE_CONTRACT and
D3_CALL_POSITION_CONTRACT):

  P1  v1 D3 TRUE     => v2 D3 TRUE
  P2  v1 D3 UNKNOWN  => v2 D3 in {UNKNOWN, TRUE}
  P3  every non-evidence TrajectoryFacts field identical between v1 and v2
  P4  no determined D3 value is produced from an UNPOSITIONED lower cutoff
  P5  every observed v1->v2 transition lies in the permitted set

Exit code 0 only when every property holds and at least one row was checked; nonzero otherwise (fail closed).

Usage:
  python benchmark/analysis/furthest_bottleneck_v2_property_search.py [--population standard|extended]
                                                                     [--report PATH]
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import benchmark.analysis.furthest_bottleneck as v1                    # noqa: E402
import benchmark.analysis.furthest_bottleneck_v2 as v2                 # noqa: E402
from benchmark.repo_task_eval import REPOS_DIR, defect_lines           # noqa: E402
from benchmark.repo_tasks import TASKS_BY_NAME                         # noqa: E402
from core.path_candidates import normalize                             # noqa: E402

VERIFIER = Path(__file__)
PERMITTED_TRANSITIONS = {(v1.T, v1.T), (v1.U, v1.U), (v1.U, v1.T), (v1.F, v1.F), (v1.F, v1.U), (v1.F, v1.T)}
SINGLE_TASK = "mathlib_divide_zero"
DUO_SEED = {"pkg/a.py": "def alpha(x):\n    return x + 0\n", "pkg/b.py": "def beta(y):\n    return y * 1\n"}
DUO_REFERENCE = {"pkg/a.py": "def alpha(x):\n    return x + 1\n", "pkg/b.py": "def beta(y):\n    return y * 2\n"}


class _StubReplayer:
    """Deterministic stand-in for the oracle. No workspace, no subprocess, no experiment evidence."""

    def run(self, task, files):
        return v1.U, "stub"


# ============================================================================= deterministic synthetic generators
def _diagnose(rnd: int, path: str, success: bool) -> dict:
    return {"round": rnd, "tool": "diagnose", "args": {"path": path, "target": "divide"},
            "success": success, "result_head": ""}


def _edit(rnd: int, path: str, success: bool) -> dict:
    return {"round": rnd, "tool": "edit_symbol", "success": success, "result_head": "",
            "args": {"path": path, "selector_kind": "python_symbol", "target": "divide", "replacement": "x"}}


def _read(rnd: int, path: str) -> dict:
    return {"round": rnd, "tool": "read_file", "args": {"path": path}, "success": True, "result_head": ""}


def _record(path: str, refused: str | None = None) -> dict:
    return {"path": path, "success": refused is None, "refused": refused, "pre_read": True,
            "evidence_head": "", "seed_span": None, "localized": False, "hits_defect": False}


def _rejection(path: str) -> dict:
    return {"reason": "evidence_requires_read", "tool": "diagnose", "path": path, "round": 0, "outcome": "unresolved"}


def _view_sets(paths: tuple[str, ...], extended: bool) -> list[list[dict]]:
    out: list[list[dict]] = []
    for p in paths:
        out += [[], [{"round": 1, "path": p, "complete": True}], [{"round": 2, "path": p, "complete": True}],
                [{"round": 3, "path": p, "complete": True}], [{"round": 4, "path": p, "complete": True}],
                [{"round": 1, "path": p, "complete": False}], [{"round": 1, "path": p, "complete": None}],
                [{"round": "x", "path": p, "complete": True}],
                [{"round": 1, "path": p, "complete": False}, {"round": 3, "path": p, "complete": True}],
                [{"round": 3, "path": p, "complete": True}, {"round": 1, "path": p, "complete": True}],
                [{"path": p, "complete": True}],
                [{"round": 2, "path": p, "complete": True}, {"round": 2, "path": p, "complete": False}],
                [{"round": 0, "path": p, "complete": True}],
                [{"round": 1, "path": p, "complete": True}, {"round": 4, "path": p, "complete": True}],
                [{"round": True, "path": p, "complete": True}],
                [{"round": 5, "path": p, "complete": None}, {"round": 1, "path": p, "complete": False}]]
        if extended:
            out += [[{"round": 6, "path": p, "complete": True}],
                    [{"round": 2, "path": p, "complete": None}, {"round": 5, "path": p, "complete": True}]]
    return out


def _attempt_sets(paths: tuple[str, ...]) -> list[list[dict]]:
    kinds = (_diagnose, _edit)
    singles = [[k(r, p, s)] for k in kinds for r in (1, 2, 3) for p in paths for s in (True, False)]
    pairs = [[k1(r1, p1, s1), k2(r2, p2, s2)]
             for k1, k2 in itertools.product(kinds, repeat=2)
             for r1, r2 in ((1, 1), (1, 2), (2, 3), (1, 3), (3, 3))
             for p1, p2 in itertools.product(paths, repeat=2)
             for s1, s2 in itertools.product((True, False), repeat=2)]
    triples = [[k1(r1, paths[0], s1), k2(r2, paths[0], s2), k3(r3, paths[-1], s3)]
               for k1, k2, k3 in itertools.product(kinds, repeat=3)
               for r1, r2, r3 in ((1, 2, 3), (1, 1, 2), (2, 2, 2), (1, 3, 3))
               for s1, s2, s3 in itertools.product((True, False), repeat=3)]
    return singles + pairs + triples + [[]]


def _refusal_patterns(calls: list[dict]) -> list[tuple[list[dict] | None, list[dict] | None]]:
    diagnoses = [c for c in calls if c["tool"] == "diagnose"]
    patterns: list[tuple[list[dict] | None, list[dict] | None]] = [(None, None)]
    for flags in itertools.product((None, "evidence_requires_read"), repeat=len(diagnoses)):
        records = [_record(normalize(str(c["args"]["path"])), f) for c, f in zip(diagnoses, flags)]
        patterns.append((records, [_rejection(r["path"]) for r in records if r["refused"]]))
        if records:
            patterns.append((records, []))          # count mismatch: the stream must degrade to UNKNOWN
    return patterns


# ============================================================================= the search
def _check_domain(paths: tuple[str, ...], task, repos_dir: Path, extended: bool, summary: dict) -> None:
    scope = v2.d1_region_files(task, repos_dir, defect_lines, normalize)
    if scope != list(paths):
        summary["violations"].append({"kind": "domain_mismatch", "scope": scope, "expected": list(paths)})
        return
    census: dict[str, int] = {}
    checked = 0
    for calls in _attempt_sets(paths):
        for records, rejections in _refusal_patterns(calls):
            for views in _view_sets(paths, extended):
                row = {"calls": [_read(1, paths[0])] + list(calls), "read_views": views,
                       "damaged_files": [], "invalid_gold_files": [], "agent_escalation": None,
                       "model_claimed_done": True, "rounds": 6}
                if records is not None:
                    row["diagnoses"], row["guard_rejections"] = records, rejections
                if v2.producer_envelope_violations(row) or v2.call_position_violations(row, scope, normalize):
                    continue
                checked += 1
                base = v1.extract_facts(row, task, _StubReplayer(), defect_lines, repos_dir, normalize, None)
                facts, _descriptive = v2.extract_facts_v2(row, task, _StubReplayer(), defect_lines, repos_dir,
                                                          normalize, None)
                census[f"{base.evidence.value}->{facts.evidence.value}"] = \
                    census.get(f"{base.evidence.value}->{facts.evidence.value}", 0) + 1
                if base.evidence is v1.T and facts.evidence is not v1.T:
                    summary["violations"].append({"kind": "P1", "calls": row["calls"], "views": views})
                if base.evidence is v1.U and facts.evidence is v1.F:
                    summary["violations"].append({"kind": "P2", "calls": row["calls"], "views": views})
                differing = [f.name for f in dataclasses.fields(v1.TrajectoryFacts)
                             if f.name != "evidence" and getattr(base, f.name) != getattr(facts, f.name)]
                if differing:
                    summary["violations"].append({"kind": "P3", "fields": differing, "calls": row["calls"]})
                if (base.evidence, facts.evidence) not in PERMITTED_TRANSITIONS:
                    summary["violations"].append({"kind": "P5", "transition":
                                                  f"{base.evidence.value}->{facts.evidence.value}"})
                for g in scope:
                    if v2.cutoff_bounds(row, g, normalize)[0] == v2.UNPOSITIONED and \
                            v2.d3_file(row, g, normalize) is not v1.U:
                        summary["violations"].append({"kind": "P4", "file": g, "calls": row["calls"]})
    domain = "+".join(paths)
    summary["domains"][domain] = {"rows_checked": checked, "transition_census": census}
    summary["rows_checked"] += checked
    for key, count in census.items():
        summary["transition_census"][key] = summary["transition_census"].get(key, 0) + count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--population", choices=("standard", "extended"), default="standard",
                        help="'extended' adds two view shapes per path; the generator stays fully enumerated")
    parser.add_argument("--report", type=Path, default=None, help="write the JSON summary here (output only)")
    parser.add_argument("--commit", default="", help="candidate commit SHA, recorded in the summary")
    args = parser.parse_args(argv)
    extended = args.population == "extended"

    summary: dict = {
        "verifier": VERIFIER.name,
        "verifier_sha256": hashlib.sha256(VERIFIER.read_bytes()).hexdigest(),
        "candidate_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "benchmark/analysis/furthest_bottleneck_taxonomy_v2.md",
            "benchmark/analysis/furthest_bottleneck_v2.py",
            "benchmark/analysis/furthest_bottleneck_v2_mutations.py",
            "tests/test_furthest_bottleneck_v2.py",
            "tests/test_producer_call_round_contract.py")},
        "commit": args.commit,
        "population": args.population,
        "deterministic": True,
        "seed": None,          # the generator is fully enumerated; no randomness is used
        "valid_domain": "D3_PRODUCER_ENVELOPE_CONTRACT and D3_CALL_POSITION_CONTRACT",
        "permitted_transitions": sorted(f"{a.value}->{b.value}" for a, b in PERMITTED_TRANSITIONS),
        "rows_checked": 0, "transition_census": {}, "domains": {}, "violations": [],
    }

    _check_domain((normalize(TASKS_BY_NAME[SINGLE_TASK].gold_files[0]),), TASKS_BY_NAME[SINGLE_TASK],
                  REPOS_DIR, extended, summary)

    with tempfile.TemporaryDirectory(prefix="fbv2-property-") as tmp:
        repos = Path(tmp)
        (repos / "duo" / "pkg").mkdir(parents=True)
        for rel, text in DUO_SEED.items():
            (repos / "duo" / rel).write_text(text, encoding="utf-8")
        duo = SimpleNamespace(name="duo", repo="duo", gold_files=tuple(DUO_SEED), reference_patch=dict(DUO_REFERENCE))
        _check_domain(tuple(DUO_SEED), duo, repos, extended, summary)
        shutil.rmtree(repos / "duo", ignore_errors=True)

    summary["violation_count"] = len(summary["violations"])
    summary["determined_from_unpositioned"] = sum(1 for v in summary["violations"] if v["kind"] == "P4")
    summary["passed"] = summary["violation_count"] == 0 and summary["rows_checked"] > 0
    text = json.dumps(summary, indent=2, default=str)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text if summary["violations"] else json.dumps(
        {k: summary[k] for k in ("verifier", "verifier_sha256", "commit", "population", "rows_checked",
                                 "transition_census", "violation_count", "determined_from_unpositioned", "passed")},
        indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
