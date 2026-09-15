from __future__ import annotations

from core.logic_layer import LogicLayer, LogicRule


def test_classify_factual_query():
    layer = LogicLayer()
    assert layer.classify_query("What files were read?") == "factual"


def test_classify_constraint_query():
    layer = LogicLayer()
    assert layer.classify_query("Files must stay in workspace") == "constraint"


def test_classify_procedural_query():
    layer = LogicLayer()
    assert layer.classify_query("How to run tests?") == "procedural"


def test_query_applies_matching_rule():
    layer = LogicLayer()
    layer.add_rule(LogicRule(
        name="upper",
        query_types=["factual"],
        condition=lambda ctx: True,
        transform=lambda notes: [{"content": n["content"].upper()} for n in notes],
    ))
    results = layer.query([{"content": "hello"}], "factual")
    assert results[0]["content"] == "HELLO"


def test_query_skips_non_matching_rule():
    layer = LogicLayer()
    layer.add_rule(LogicRule(
        name="upper",
        query_types=["constraint"],
        condition=lambda ctx: True,
        transform=lambda notes: [{"content": n["content"].upper()} for n in notes],
    ))
    results = layer.query([{"content": "hello"}], "factual")
    assert results == []
