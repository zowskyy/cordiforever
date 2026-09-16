"""Shared synthetic fixtures for the S2 paired-substrate suites.

Everything here is synthetic: no model, no Ollama, no corpus, no preserved row. Populations are
built through the frozen MNT-09 admission mechanism, never by hand, so the tests exercise the real
ownership boundary rather than a convenient stand-in.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.analysis import taxonomy_population_registry_v1 as mnt09  # noqa: E402

TASKS = [f"synth_task_{i:02d}" for i in range(20)]
INC_GATE = "1" * 64
CHAL_GATE = "2" * 64
CORPUS = "c" * 64
HARNESS_OLD = "a" * 64
HARNESS_NEW = "b" * 64


def conditions_with(*names: str) -> dict[str, Any]:
    import benchmark.repo_task_eval as rte
    conditions = copy.deepcopy(dict(rte.CONDITIONS))
    base = dict(conditions["qwen_selectorkind"]["overrides"])
    for name in names:
        conditions[name] = {"model": f"{name}:0b", "overrides": dict(base)}
    return conditions


def row(task: str, *, condition: str, gate: str, harness: str, oracle_passed: bool,
        model: str = "synthetic:0b", **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "task": task,
        "split": "dev",
        "condition": condition,
        "model": model,
        "model_digest": "d" * 64,
        "calls": [{"tool": "read_file", "round": 1, "args": {"path": "a.py"}, "success": True}],
        "fingerprint": f"fp_{condition}_{task}",
        "experiment": {"gate": {"sha256": gate}, "corpus_sha256": CORPUS, "harness_sha256": harness},
        "expected_outcome": "verified_done",
        "oracle_passed": oracle_passed,
        "lane_false_verified": False,
        "model_false_done_claim": False,
        "false_completion_on_insufficient_evidence": False,
        "damaged_files": [],
        "stray_files": [],
        "files_mutated": [],
        "invalid_actions": [],
        "guard_rejections": [],
        "tool_calls": 3,
        "rounds": 5,
        "model_replies": 5,
        "seconds": 40.0,
        "prompt_tokens": 7000,
    }
    record.update(overrides)
    return record


def prr(population_id: str, arm_id: str, condition: str, gate: str, *,
        new_data: bool = True) -> dict[str, Any]:
    record: dict[str, Any] = {
        "population_id": population_id,
        "methodology": dict(mnt09.FROZEN_METHODOLOGY),
        "new_data_application": new_data,
        "arms": [{"arm_id": arm_id, "role": "primary", "condition": condition,
                  "gate_sha256": gate, "split": "dev"}],
        "task_set": list(TASKS),
        "expected_rows_per_arm": len(TASKS),
        "expected_total_rows": len(TASKS),
        "input_contract_version": mnt09.INPUT_CONTRACT_V1,
        "registration_ref": {"gate_sha256": gate, "commit": "0" * 40},
    }
    return record


def admit(arm_id: str, condition: str, gate: str, harness: str,
          passes: Sequence[str], conditions: Mapping[str, Any],
          row_overrides: Mapping[str, Mapping[str, Any]] | None = None) -> mnt09.Admission:
    overrides = dict(row_overrides or {})
    rows = [(index, row(task, condition=condition, gate=gate, harness=harness,
                        oracle_passed=task in passes, **overrides.get(task, {})))
            for index, task in enumerate(TASKS, start=1)]
    registration = mnt09.load_prr(prr(f"POP_{arm_id}", arm_id, condition, gate))
    return mnt09.admit_population(registration, rows, conditions)


#: Synthetic gold-file map. Supplied explicitly so the default fixtures exercise the KNOWN
#: out-of-scope path; the UNKNOWN path has its own dedicated tests.
GOLD_FILES = {task: (f"pkg/{task}.py",) for task in TASKS}


def classification(arm_id: str, task: str, label: str, *, d3: str = "FALSE",
                   sub_label: str | None = None) -> dict[str, Any]:
    return {"arm": arm_id, "task": task, "label": label, "sub_label": sub_label,
            "d3_evidence": d3, "undetermined_cause": None, "f6_subtype": None}


def classifications_for(arm_id: str, tasks: Sequence[str], label: str = "F4",
                        d3: str = "FALSE") -> dict[tuple[str, str], dict[str, Any]]:
    return {(arm_id, task): classification(arm_id, task, label, d3=d3) for task in tasks}
