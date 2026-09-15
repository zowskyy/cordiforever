from __future__ import annotations

import json
import shutil
from pathlib import Path

from benchmark import protocol_probe_eval as ppe
from core.messages import Message
from tests.test_agent import _build_agent_with_schema


def test_probe_system_prompt_matches_what_the_loop_sends(tmp_path):
    shutil.copytree(ppe.REPOS_DIR / ppe.PROBE_REPO, tmp_path / "ws", ignore=shutil.ignore_patterns("__pycache__"))
    ctx, reg = _build_agent_with_schema(tmp_path / "ws", [Message("assistant", "done")], profile="lite", compact_schema=True,
                                        config={"calibration": {"repo_tools": True}})
    seen = []
    model = ctx.plugins["ollama_model"]
    original = model.chat
    model.chat = lambda messages, tools: (seen.append(messages[0].content), original(messages, tools))[1]
    try:
        ctx.plugins["agent_loop"].run("hello")
    finally:
        reg.stop_all()
    assert seen[0] == ppe.system_prompt()


def test_probes_target_real_repository_content():
    from core.repo_index import RepositoryIndex

    index = RepositoryIndex(ppe.REPOS_DIR / ppe.PROBE_REPO)
    names = [p.name for p in ppe.PROBES]
    assert len(names) == len(set(names)) == 15
    for probe in ppe.PROBES:
        for key in ("path", "target"):
            value = probe.args.get(key)
            if value and value.endswith(".py"):
                assert value in index.files, probe.name
        for key in ("name", "symbol"):
            if probe.args.get(key):
                assert index.definitions(probe.args[key]), probe.name
    assert {p.tool for p in ppe.PROBES} >= {"read_file", "list_directory", "repo_outline", "find_symbol", "find_references", "find_tests", "dependency_cone", "delete_file"}


def test_args_match_normalizes_paths_and_requires_expected_keys():
    assert ppe.args_match({"path": "mathlib/operations.py"}, {"path": "./mathlib/operations.py"})
    assert ppe.args_match({}, {"anything": 1})
    assert not ppe.args_match({"name": "subtract"}, {"name": "add"})
    assert not ppe.args_match({"target": "calculator.py"}, {})


def test_conditions_enable_repo_tools_and_keep_named_factor_isolation():
    assert all(cfg["overrides"]["repo_tools"] is True for cfg in ppe.CONDITIONS.values())
    gemma, qwen = ppe.CONDITIONS["gemma_constrained"], ppe.CONDITIONS["qwen_constrained"]
    assert gemma["overrides"] == qwen["overrides"] and gemma["model"] != qwen["model"]


def test_summary_separates_choice_encoding_and_execution():
    rows = [
        {"probe": "a", "chosen_tool": "read_file", "semantic_choice_correct": True, "protocol_encoding": "text_json", "executed": True},
        {"probe": "b", "chosen_tool": "read_file", "semantic_choice_correct": False, "protocol_encoding": "text_json", "executed": True},
        {"probe": "c", "chosen_tool": None, "semantic_choice_correct": False, "protocol_encoding": "invalid", "executed": False},
        {"probe": "d", "chosen_tool": "find_symbol", "semantic_choice_correct": True, "protocol_encoding": "native", "executed": False},
    ]
    summary = ppe.summarize(rows)
    assert summary["semantic_choice_correct"] == "2/4"
    assert summary["protocol_encodings"] == {"text_json": 2, "invalid": 1, "native": 1}
    assert summary["correct_and_executed"] == "1/4"
    assert summary["choice_correct_given_valid_encoding"] == "2/3"
    assert summary["wrong_choices"] == {"b": "read_file", "c": None}
