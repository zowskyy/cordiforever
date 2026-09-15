from __future__ import annotations

import json

import pytest

from benchmark import tool_call_eval as tce
from core.errors import ModelError
from core.messages import Message


def _classify(task_prompt, raw):
    task = next(t for t in tce.TASKS if t.prompt == task_prompt)
    router = tce.build_router()
    return tce.classify(task, raw, router, router.get_model_tools())


@pytest.mark.parametrize("prompt,raw,expected", [
    ("Read config.json", '{"tool": "read", "args": {"path": "./config.json"}}', "ok"),
    ("Read config.json", '{"tool": "list", "args": {"path": "."}}', "wrong_tool"),
    ("Read config.json", '{"tool": "read", "args": {"path": "settings.json"}}', "wrong_path"),
    ("Create hello.py that prints hello", '{"tool": "write", "args": {"path": "hello.py", "content": "x = 1"}}', "wrong_content"),
    ("Read config.json", '{"tool": "done", "args": {"summary": "read it"}}', "premature_done"),
    ("Fix the bug in app.py", '{"tool": "write", "args": {"path": "app.py", "content": "fixed"}}', "missing_prerequisite_read"),
    ("Explain what lib/parser.py does", '{"tool": "write", "args": {"path": "lib/parser.py", "content": "x"}}', "wrong_tool"),
    ("Read config.json", "I cannot access files.", "invalid_action"),
])
def test_classify_categories(prompt, raw, expected):
    assert _classify(prompt, raw)[0] == expected


class _ScriptedModel:
    """Replaces OllamaModel inside the eval; fails once to simulate a killed/timeout sample."""

    calls = 0

    def __init__(self, model, options=None, response_format=None):
        self.last_token_usage = None
        self.last_done_reason = "stop"

    def chat(self, messages, tools):
        type(self).calls += 1
        if type(self).calls == 2:
            raise ModelError("Could not reach Ollama: Read timed out.")
        return Message("assistant", '{"tool": "list", "args": {"path": "."}}')


def _config():
    return {"model": "fake", "options": {"temperature": 0.0}, "constrain": True, "prompt_sha": "p", "schema_sha": "s", "tasks_sha": "t", "samples": 1}


def test_checkpoint_resume_skips_recorded_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(tce, "OllamaModel", _ScriptedModel)
    _ScriptedModel.calls = 0
    out = tmp_path / "eval.jsonl"
    remaining = tce.run(_config(), "system", 1, out, max_new=4, include_probes=False)
    assert remaining == len(tce.TASKS) - 4
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert rows[1]["category"] == "model_error" and rows[1]["detail"] == "timeout"

    with out.open("a", encoding="utf-8") as fh:
        fh.write('{"config_key": "partial line from a killed pro')

    remaining = tce.run(_config(), "system", 1, out, max_new=None, include_probes=False)
    assert remaining == 0
    recorded = tce.load_rows(out, tce.config_key(_config()))
    assert len(recorded) == len(tce.TASKS)
    assert len({(r["prompt"], r["sample"]) for r in recorded}) == len(tce.TASKS)
    assert _ScriptedModel.calls == len(tce.TASKS)


def test_summary_marks_incomplete_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(tce, "OllamaModel", _ScriptedModel)
    _ScriptedModel.calls = 0
    out = tmp_path / "eval.jsonl"
    tce.run(_config(), "system", 1, out, max_new=3, include_probes=False)
    summary = tce.summarize(tce.load_rows(out, tce.config_key(_config())), {"dev": len(tce.TASKS), "probe": 0})
    assert summary["dev"]["n"] == 3
    assert summary["dev"]["complete"] is False
    assert summary["dev"]["categories"]["model_error"] == 1
