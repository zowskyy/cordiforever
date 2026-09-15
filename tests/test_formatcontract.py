"""qwen_formatcontract_v1 mechanism: exact replacement-format contract text in the edit guidance, plus model-invisible
evaluator instrumentation (edit_proposals, format_contract_shown). Edit execution and guards are unchanged."""

from __future__ import annotations

import ast
import json
import shutil
import textwrap
from pathlib import Path

from benchmark.repo_task_eval import CONDITIONS, edit_proposal_recorder, format_contract_shown
from core.messages import Message
from plugins.agent.loop import (REPLACEMENT_CONTRACT_JSON, REPLACEMENT_CONTRACT_PY, REPLACEMENT_PLACEHOLDER_JSON,
                                REPLACEMENT_PLACEHOLDER_PY, SELECTOR_KIND_EDIT_GUIDANCE)
from tests.test_agent import _build_agent_with_schema, _tc_compact

ROOT = Path(__file__).resolve().parents[1]
REPOS = ROOT / "benchmark" / "repos"
GATE = (ROOT / "benchmark" / "gates" / "qwen_formatcontract_v1.md").read_text(encoding="utf-8")
BASE = dict(CONDITIONS["qwen_selectorkind"]["overrides"])
TREAT = dict(CONDITIONS["qwen_formatcontract"]["overrides"])
FIX = "def slugify(text):\n    kept = ''.join(ch for ch in text if ch.isalnum() or ch in ' -')\n    return kept.strip().lower().replace(' ', '-')"
LONG_FIX = FIX + "\n" + "\n".join(f"    # padding line {i} to exceed the 300-character argument summary" for i in range(6))


def call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def run(tmp_path, calibration, responses, observe=None):
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / "textkit", workspace, ignore=shutil.ignore_patterns("__pycache__"))
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = 12
    sent: list[str] = []
    model = ctx.plugins["ollama_model"]
    original = model.chat

    def recording(messages, tools, _orig=original):
        sent.extend(m.content or "" for m in messages)
        return _orig(messages, tools)

    model.chat = recording
    events: list[tuple[str, dict]] = []
    proposals, recorder = edit_proposal_recorder(workspace)

    def on_event(e):
        payload = dict(e.payload or {})
        events.append((e.type, payload))
        recorder(e.type, payload)

    ctx.events.on("*", on_event)
    try:
        ctx.plugins["agent_loop"].run("slugify must remove punctuation.")
    finally:
        reg.stop_all()
    return workspace, sent, proposals, events, ctx


PREFIX = [call("read", path="textkit/slugify.py"),
          call("diagnose", path="textkit/slugify.py", target="slugify", cause="keeps punctuation", change="remove it")]


def edit(replacement):
    return call("edit", path="textkit/slugify.py", selector_kind="python_symbol", target="slugify", replacement=replacement)


def system_text(ctx) -> str:
    return "\n".join(m.content for m in ctx.messages if m.role == "system")


def test_contract_strings_are_the_frozen_gate_text():
    assert REPLACEMENT_CONTRACT_PY in GATE and REPLACEMENT_CONTRACT_JSON in GATE
    assert "no Markdown code fences" in REPLACEMENT_CONTRACT_PY and "async def" in REPLACEMENT_CONTRACT_PY


def test_single_factor_condition():
    assert TREAT == {**BASE, "replacement_format_contract": True}
    assert not TREAT.get("ast_noop_refusal") and not TREAT.get("completion_requires_mutation_success")


def test_treatment_guidance_replaces_exactly_the_two_placeholders(tmp_path):
    _, sent, _, _, ctx = run(tmp_path, TREAT, [call("done", summary="x")])
    text = system_text(ctx)
    expected = SELECTOR_KIND_EDIT_GUIDANCE.replace(REPLACEMENT_PLACEHOLDER_PY, REPLACEMENT_CONTRACT_PY).replace(REPLACEMENT_PLACEHOLDER_JSON, REPLACEMENT_CONTRACT_JSON)
    assert json.dumps(expected, ensure_ascii=False)[1:-1] in text
    assert json.dumps(REPLACEMENT_PLACEHOLDER_PY, ensure_ascii=False)[1:-1] not in text
    assert json.dumps(REPLACEMENT_PLACEHOLDER_JSON, ensure_ascii=False)[1:-1] not in text
    assert format_contract_shown(sent) is True


def test_control_guidance_is_unchanged(tmp_path):
    _, sent, _, _, ctx = run(tmp_path, BASE, [call("done", summary="x")])
    text = system_text(ctx)
    assert json.dumps(SELECTOR_KIND_EDIT_GUIDANCE, ensure_ascii=False)[1:-1] in text
    assert format_contract_shown(sent) is False


def test_guidance_differs_only_in_the_two_placeholders(tmp_path):
    _, _, _, _, ctx_t = run(tmp_path / "t", TREAT, [call("done", summary="x")])
    _, _, _, _, ctx_c = run(tmp_path / "c", BASE, [call("done", summary="x")])
    treat, control = system_text(ctx_t), system_text(ctx_c)
    enc = lambda s: json.dumps(s, ensure_ascii=False)[1:-1]  # noqa: E731
    assert treat.replace(enc(REPLACEMENT_CONTRACT_PY), enc(REPLACEMENT_PLACEHOLDER_PY)).replace(enc(REPLACEMENT_CONTRACT_JSON), enc(REPLACEMENT_PLACEHOLDER_JSON)) == control


def test_contract_requires_explicit_selector_kind(tmp_path):
    no_kind = {**TREAT, "explicit_selector_kind": False}
    _, sent, _, _, _ = run(tmp_path, no_kind, [call("done", summary="x")])
    assert format_contract_shown(sent) is False


def test_guards_and_messages_unchanged_for_malformed_replacements(tmp_path):
    fenced = "```python\n" + FIX + "\n```"
    results = []
    for arm, calibration in (("c", BASE), ("t", TREAT)):
        _, _, proposals, events, _ = run(tmp_path / arm, calibration, PREFIX + [edit(fenced), call("done", summary="x")])
        edit_results = [p for t, p in events if t == "tool.result" and p.get("tool") == "edit_symbol"]
        results.append([(r["success"], json.loads(r["result"]).get("error")) for r in edit_results])
        assert [p["success"] for p in proposals] == [False]
    assert results[0] == results[1] and results[0][0][0] is False


def test_no_repair_valid_edit_is_structurally_preserved(tmp_path):
    workspace, _, proposals, _, _ = run(tmp_path, TREAT, PREFIX + [edit(FIX), call("done", summary="x")])
    written = (workspace / "textkit" / "slugify.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(written).body if isinstance(n, ast.FunctionDef) and n.name == "slugify")
    assert ast.dump(node) == ast.dump(ast.parse(textwrap.dedent(FIX)).body[0])
    assert proposals[0]["after_text"] == written


def test_edit_proposals_are_untruncated_and_pair_with_calls(tmp_path):
    workspace, _, proposals, events, _ = run(tmp_path, TREAT, PREFIX + [edit("to_title_case"), edit(LONG_FIX), call("done", summary="x")])
    edit_results = [p for t, p in events if t == "tool.result" and p.get("tool") == "edit_symbol"]
    assert len(proposals) == len(edit_results) == 2
    assert [p["success"] for p in proposals] == [r["success"] for r in edit_results] == [False, True]
    assert proposals[1]["replacement"] == LONG_FIX and len(LONG_FIX) > 300
    assert proposals[0]["after_text"] is None
    assert proposals[1]["after_text"] == (workspace / "textkit" / "slugify.py").read_text(encoding="utf-8")
    assert {k for k in proposals[0]} == {"path", "selector_kind", "target", "replacement", "success", "after_text"}


def test_format_contract_shown_requires_both_exact_strings():
    assert format_contract_shown([REPLACEMENT_CONTRACT_PY + REPLACEMENT_CONTRACT_JSON])
    assert format_contract_shown([json.dumps({"content": REPLACEMENT_CONTRACT_PY + REPLACEMENT_CONTRACT_JSON}, ensure_ascii=False)])
    assert not format_contract_shown([REPLACEMENT_CONTRACT_PY])
    assert not format_contract_shown([REPLACEMENT_CONTRACT_JSON])
    assert not format_contract_shown([REPLACEMENT_CONTRACT_PY.replace("Markdown code fences", "fences") + REPLACEMENT_CONTRACT_JSON])
    assert not format_contract_shown([])
