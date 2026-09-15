from __future__ import annotations

from benchmark.agent_task_eval import rejection_outcomes, unread_source_writes


def _result(tool, path, success=True):
    return ("tool.result", {"tool": tool, "arguments": {"path": path}, "success": success})


def test_every_corpus_task_has_an_eligible_bounded_spec():
    from benchmark.agent_task_eval import LANE_SPECS, TASKS
    from core.bounded_task import eligibility_problems

    assert set(LANE_SPECS) == {t.name for t in TASKS}
    for task in TASKS:
        spec = LANE_SPECS[task.name](task)
        assert eligibility_problems(spec) == [], task.name
        assert spec.instruction == task.prompt
        assert set(spec.mutable_paths) <= set(task.seed) | set(task.expected_new), task.name


def test_damaged_files_detects_structural_loss_only(tmp_path):
    from benchmark.agent_task_eval import damaged_files

    seed = {
        "config/app.json": '{"name": "demo", "port": 3000}',
        "ok.json": '{"name": "demo", "port": 3000}',
        "add.py": "def add(a, b):\n    return a - b\n",
        "fixed.py": "def add(a, b):\n    return a - b\n",
        "greetings.txt": "hello\n",
        "appended.txt": "hello\n",
        "untouched.txt": "same\n",
    }
    finals = {
        "config/app.json": "Port: 8080",
        "ok.json": '{"name": "demo", "port": 8080}',
        "add.py": "return a + b\nAdd the numbers.",
        "fixed.py": "def add(x, y):\n    return x + y\n",
        "greetings.txt": "bye\n",
        "appended.txt": "hello\nbye\n",
        "untouched.txt": "same\n",
    }
    for rel, text in finals.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    assert sorted(damaged_files(tmp_path, seed)) == ["add.py", "config/app.json", "greetings.txt"]


def test_unread_source_writes_counts_mutations_before_first_source_read():
    sources = frozenset({"docs/notes.txt"})
    blind = [_result("read_file", "notes.txt", success=False), _result("write_file", "count.txt"), _result("read_file", "count.txt")]
    assert unread_source_writes(blind, sources) == 1
    informed = [_result("read_file", "docs/notes.txt"), _result("write_file", "count.txt")]
    assert unread_source_writes(informed, sources) == 0
    assert unread_source_writes(blind, frozenset()) == 0


def _rejected(path, round_=1):
    return ("guard.rejected", {"reason": "wrong_path", "conflict": "exact_basename", "tool": "read_file", "path": path, "candidates": ["src/add.py"], "round": round_})


def test_rejection_repaired_when_same_tool_later_succeeds_on_other_path():
    timeline = [
        _rejected("add.py"),
        ("tool.invoked", {"tool_name": "read_file", "arguments": {"path": "src/add.py"}}),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "src/add.py"}, "success": True}),
    ]
    (outcome,) = rejection_outcomes(timeline)
    assert outcome["outcome"] == "repaired" and outcome["retried"] is True
    assert outcome["candidates"] == ["src/add.py"] and outcome["conflict"] == "exact_basename"


def test_rejection_repeated_when_same_path_rejected_again_or_repeat_detected():
    again = [_rejected("add.py"), ("tool.invoked", {"tool_name": "read_file", "arguments": {"path": "add.py"}}), _rejected("./add.py", 2)]
    assert [o["outcome"] for o in rejection_outcomes(again)] == ["repeated", "unresolved"]
    detected = [_rejected("add.py"), ("repeat.detected", {"calls": ['read_file:{"path": "add.py"}@v0']})]
    assert rejection_outcomes(detected)[0]["outcome"] == "repeated"


def test_unread_overwrite_is_repaired_by_later_write_to_same_path():
    timeline = [
        ("guard.rejected", {"reason": "unread_overwrite", "tool": "write_file", "path": "add.py", "round": 1}),
        ("tool.result", {"tool": "write_file", "arguments": {"path": "add.py"}, "success": True}),
    ]
    assert rejection_outcomes(timeline)[0]["outcome"] == "repaired"
    same_path_wrong = [_rejected("add.py"), ("tool.result", {"tool": "read_file", "arguments": {"path": "add.py"}, "success": True})]
    assert rejection_outcomes(same_path_wrong)[0]["outcome"] == "unresolved"


def test_wrong_path_not_repaired_by_success_on_unrelated_path():
    timeline = [
        _rejected("add.py"),
        ("tool.result", {"tool": "read_file", "arguments": {"path": "count.txt"}, "success": True}),
    ]
    assert rejection_outcomes(timeline)[0]["outcome"] == "unresolved"


def test_rejection_unresolved_when_nothing_follows():
    (outcome,) = rejection_outcomes([_rejected("add.py")])
    assert outcome == {**outcome, "outcome": "unresolved", "retried": False}
