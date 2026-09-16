"""MNT-09 test 6, Level B: historical classification identity.

Classifying the MNT-09-admitted historical population with the unmodified frozen implementation must
reproduce the authoritative EXEC-D3V2-01 artifact `benchmark/analysis/output_v2/classification_v2.jsonl`
at BYTE identity.

Byte identity is the correct criterion here rather than a weaker semantic one, because EXEC-D3V2-01
already established it for this exact artifact and operation (two fresh-process realizations produced
byte-identical bytes) and the serialization is canonical: json.dumps(sort_keys=True,
ensure_ascii=False, separators=(",", ":")) written with newline="\\n", carrying no timestamp, pid,
duration or path. This test therefore preserves a proven property instead of weakening it.

This test replays oracles on temporary copies of the seed repository, exactly as the frozen code
already does. No model is contacted, no scorer main is run, and nothing is written outside pytest's
temporary area.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import taxonomy_population_registry_v1 as reg  # noqa: E402

RESULTS = ROOT / "benchmark" / "results" / "repo_task_eval.jsonl"
AUTHORITATIVE = ROOT / "benchmark" / "analysis" / "output_v2" / "classification_v2.jsonl"
AUTHORITATIVE_SHA256 = "1fbfd30bc46900b7d15845e5916200d227ac9a618c815c55db0038ff13d7b3a6"

pytestmark = pytest.mark.skipif(not AUTHORITATIVE.is_file(),
                                reason="authoritative EXEC-D3V2-01 output_v2 tree is not present")


def _rows() -> list[tuple[int, dict]]:
    out: list[tuple[int, dict]] = []
    for number, line in enumerate(RESULTS.read_bytes().decode("utf-8").splitlines(), start=1):
        if line.strip():
            out.append((number, json.loads(line)))
    return out


def test_authoritative_artifact_is_unchanged():
    actual = hashlib.sha256(AUTHORITATIVE.read_bytes()).hexdigest()
    assert actual == AUTHORITATIVE_SHA256, "the preserved EXEC-D3V2-01 artifact has changed"


def test_6_level_b_classification_is_byte_identical_to_the_authoritative_artifact():
    from benchmark.analysis import run_furthest_bottleneck_classification_v2 as runner
    import benchmark.analysis.furthest_bottleneck as v1
    import benchmark.analysis.furthest_bottleneck_v2 as v2
    from benchmark import repo_task_eval as rte
    from core.path_candidates import normalize

    prr = reg.historical_population()
    admission = reg.admit_population(prr, _rows(), rte.CONDITIONS)

    v1.frozen_format_classifier()
    v1.frozen_edit_failure_reasons()
    runner.oracle_sanity(v1)

    records = []
    for arm in prr.arms:
        selected = admission.selection[arm.arm_id]
        for number, row in sorted(selected, key=lambda item: item[1]["task"]):
            if row.get("expected_outcome") != "verified_done" or row.get("oracle_passed") is True:
                continue
            records.append(runner.classify_trajectory(
                v1, v2, rte, normalize, arm.arm_id, arm.role, number, row))

    assert len(records) == 78

    produced = "".join(runner.dumps_line(record) + "\n" for record in records)
    produced_bytes = produced.encode("utf-8")

    assert hashlib.sha256(produced_bytes).hexdigest() == AUTHORITATIVE_SHA256
    assert produced_bytes == AUTHORITATIVE.read_bytes()
