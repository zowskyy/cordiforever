from __future__ import annotations

import json

import pytest

from core.structured_edit import EditError, apply_json_patch, parse_pointer, replace_exact, serialize_like, validate_language

BUGGY = "def add(a, b):\n    return a - b\n"


def test_replace_changes_only_the_matched_span():
    after = replace_exact(BUGGY, "return a - b", "return a + b")
    assert after == "def add(a, b):\n    return a + b\n"


@pytest.mark.parametrize("old,message", [
    ("return a * b", "not found"),
    ("", "must not be empty"),
    ("a", "matches"),
    ("return a - b", "identical"),
])
def test_replace_rejects_zero_multiple_empty_and_noop(old, message):
    new = old if message == "identical" else "x"
    with pytest.raises(EditError, match=message):
        replace_exact(BUGGY, old, new)


def test_prose_contamination_of_python_is_rejected():
    # Observed failure: gemma appended a prose sentence to add.py.
    after = replace_exact(BUGGY, "return a - b", "return a + b\n\nAdd the two numbers together.")
    with pytest.raises(EditError, match="valid Python"):
        validate_language("src/mathlib/add.py", BUGGY, after)
    validate_language("add.py", BUGGY, replace_exact(BUGGY, "return a - b", "return a + b"))


CONFIG = '{"name": "demo", "port": 3000, "nested": {"hosts": ["a", "b"], "debug": false}}'


def test_patch_port_preserves_every_unrelated_field():
    doc = json.loads(CONFIG)
    new_doc, changes = apply_json_patch(doc, {"/port": 8080})
    assert new_doc == {"name": "demo", "port": 8080, "nested": {"hosts": ["a", "b"], "debug": False}}
    assert doc["port"] == 3000
    assert changes == ["/port: 3000 -> 8080"]
    assert apply_json_patch(doc, {"port": 8080})[0] == new_doc


def test_patch_nested_add_append_and_remove():
    doc = json.loads(CONFIG)
    new_doc, changes = apply_json_patch(doc, {"/nested/debug": True, "/nested/hosts/-": "c", "/timeout": 30}, remove=["/name"])
    assert new_doc == {"port": 3000, "nested": {"hosts": ["a", "b", "c"], "debug": True}, "timeout": 30}
    assert "/name: removed" in changes


@pytest.mark.parametrize("set_values,remove,message", [
    ({"": {"port": 8080}}, None, "whole document"),
    ({"/": 1}, None, "whole document"),
    ({"/port": "8080"}, None, "refusing to replace it with a string"),
    ({"/name": {"x": 1}}, None, "refusing to replace it with a object"),
    ({"/missing/port": 1}, None, "does not exist"),
    ({"/nested/hosts/9": "z"}, None, "past the end"),
    ({"/port/x": 1}, None, "parent is a number"),
    ({}, ["/absent"], "nothing to remove"),
    ({}, [], "Nothing to change"),
])
def test_destructive_or_invalid_patches_are_impossible(set_values, remove, message):
    doc = json.loads(CONFIG)
    with pytest.raises(EditError, match=message):
        apply_json_patch(doc, set_values, remove)
    assert doc == json.loads(CONFIG)


def test_pointer_escapes():
    assert parse_pointer("/a~1b/c~0d") == ["a/b", "c~d"]
    with pytest.raises(EditError):
        parse_pointer("/a//b")


def test_serialize_keeps_indentation_and_trailing_newline():
    pretty = '{\n  "name": "demo",\n  "port": 3000\n}\n'
    assert serialize_like(pretty, {"name": "demo", "port": 8080}) == '{\n  "name": "demo",\n  "port": 8080\n}\n'
    assert serialize_like(CONFIG, {"port": 1}) == '{"port": 1}'


def test_json_validation_rejects_breaking_edit():
    with pytest.raises(EditError, match="valid JSON"):
        validate_language("config/app.json", CONFIG, "Port: 8080")
