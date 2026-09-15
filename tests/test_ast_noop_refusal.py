"""qwen_astnoop_v1 mechanism: refuse python_symbol replacements whose normalized AST equals the current definition."""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from core.messages import Message
from core.structured_edit import STRUCTURAL_NOOP_MESSAGE, EditError, is_structural_noop, replace_python_symbol, target_definition_node
from tests.test_agent import _build_agent_with_schema, _tc_compact

REPOS = Path(__file__).resolve().parents[1] / "benchmark" / "repos"
SLUGIFY = (REPOS / "textkit" / "textkit" / "slugify.py").read_text(encoding="utf-8")
BASE = {"diagnose_before_mutation": True, "full_read_views": True, "read_before_evidence": True, "evidence_extraction": True,
        "require_read_before_write": True, "localized_edits": True, "explicit_selector_kind": True}
NOOP = {**BASE, "ast_noop_refusal": True}


def noop(source: str, target: str, replacement: str) -> bool:
    return is_structural_noop(target_definition_node(ast.parse(source), target), ast.parse(replacement))


SOURCE = '''X = 1


class Store:
    def total(self):
        return "a"


def slug(text):
    return text.replace(" ", "-")


def repeat(text):
    return (text + "a") * 2
'''


@pytest.mark.parametrize("target,replacement", [
    ("slug", "def slug(text):\n    return text.replace(' ', '-')\n"),                     # quote style only
    ("slug", "def slug( text ):\n    return text.replace(\" \",   \"-\")"),               # whitespace
    ("slug", "def slug(text):\n    return (\n        text.replace(' ', '-')\n    )"),    # reformatted
    ("Store.total", "def total(self):\n    return 'a'"),                                   # method, re-indented
    ("X", "X  =  1"),                                                                       # assignment
])
def test_structural_noops_are_detected(target, replacement):
    assert noop(SOURCE, target, replacement)


@pytest.mark.parametrize("target,replacement", [
    ("slug", "def slug(text):\n    return text.replace(' ', '_')"),                        # behavior change
    ("slug", 'def slug(text):\n    """Doc."""\n    return text.replace(" ", "-")'),          # docstring is structural
    ("slug", "@staticmethod\ndef slug(text):\n    return text.replace(' ', '-')"),         # decorator is structural
    ("slug", "def slug(text):\n    return text.replace(' ', '-')\n\n\ndef extra():\n    return 1"),  # two statements
    ("X", "X = 1 + 0"),                                                                     # no constant folding
    ("slug", "def slug(value):\n    return value.replace(' ', '-')"),                      # no renaming analysis
    ("repeat", "def repeat(text):\n    return text + 'a' * 2"),                                # precedence differs structurally
])
def test_structural_changes_are_not_noops(target, replacement):
    assert not noop(SOURCE, target, replacement)


def test_replace_python_symbol_refuses_only_with_the_flag():
    restated = "def slugify(text):\n    return text.strip().lower().replace(' ', '-')"
    with pytest.raises(EditError) as raised:
        replace_python_symbol("s.py", SLUGIFY, "slugify", restated, refuse_structural_noop=True)
    assert str(raised.value) == STRUCTURAL_NOOP_MESSAGE
    new, span = replace_python_symbol("s.py", SLUGIFY, "slugify", restated)
    assert span == (1, 2) and "replace(' ', '-')" in new


def test_refusal_message_is_neutral():
    for word in ("slugify", "strip", "punctuation", "line", "should", "instead", "quote"):
        assert word not in STRUCTURAL_NOOP_MESSAGE.lower()


def _call(tool, **args):
    return Message("assistant", "", tool_calls=[_tc_compact(tool, args)])


def _run(tmp_path, calibration, replacements):
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / "textkit", workspace, ignore=shutil.ignore_patterns("__pycache__"))
    responses = [_call("read", path="textkit/slugify.py"),
                 _call("diagnose", path="textkit/slugify.py", target="slugify", cause="keeps punctuation", change="remove it")]
    responses += [_call("edit", path="textkit/slugify.py", selector_kind="python_symbol", target="slugify", replacement=r) for r in replacements]
    responses.append(_call("done", summary="x"))
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": calibration})
    ctx.plugins["agent_loop"].max_rounds = 12
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("slugify must remove punctuation.")
    finally:
        reg.stop_all()
    edits = [p for t, p in events if t == "tool.result" and p.get("tool") == "edit_symbol"]
    return workspace, edits


RESTATED = "def slugify(text):\n    return text.strip().lower().replace(' ', '-')"
SUBSTANTIVE = "def slugify(text):\n    kept = ''.join(ch for ch in text if ch.isalnum() or ch in ' -')\n    return kept.strip().lower().replace(' ', '-')"


def test_loop_refuses_restatement_then_accepts_substantive_edit(tmp_path):
    workspace, edits = _run(tmp_path, NOOP, [RESTATED, SUBSTANTIVE])
    assert [e["success"] for e in edits] == [False, True]
    assert json.loads(edits[0]["result"])["error"] == STRUCTURAL_NOOP_MESSAGE
    assert "isalnum" in (workspace / "textkit" / "slugify.py").read_text(encoding="utf-8")


def test_control_arm_accepts_the_restatement(tmp_path):
    workspace, edits = _run(tmp_path, BASE, [RESTATED])
    assert [e["success"] for e in edits] == [True]
    assert "replace(' ', '-')" in (workspace / "textkit" / "slugify.py").read_text(encoding="utf-8")


def test_json_pointer_edits_are_unaffected(tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(REPOS / "configsvc", workspace, ignore=shutil.ignore_patterns("__pycache__"))
    responses = [_call("read", path="config/app.json"),
                 _call("diagnose", path="config/app.json", target="/port", cause="c", change="x"),
                 _call("edit", path="config/app.json", selector_kind="json_pointer", target="/port", replacement="3000"),
                 _call("done", summary="x")]
    ctx, reg = _build_agent_with_schema(workspace, responses, profile="lite", compact_schema=True, config={"calibration": NOOP})
    ctx.plugins["agent_loop"].max_rounds = 12
    events: list[tuple[str, dict]] = []
    ctx.events.on("*", lambda e: events.append((e.type, e.payload)))
    try:
        ctx.plugins["agent_loop"].run("x")
    finally:
        reg.stop_all()
    edit = [p for t, p in events if t == "tool.result" and p.get("tool") == "edit_symbol"][0]
    assert edit["success"] is False and "nothing would change" in json.loads(edit["result"])["error"]
