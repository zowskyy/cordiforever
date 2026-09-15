from __future__ import annotations

import pytest

from core.intent_router import IntentRouter


def test_route_unknown_when_no_keywords_match():
    router = IntentRouter()
    route = router.route("asdf qwerty zxcv")
    assert route.goal_scope == "unknown"
    assert route.action_type == "unknown"
    assert route.entity_type == "unknown"


def test_route_confidence_scoring_partial_match():
    router = IntentRouter()
    route = router.route("show files")
    assert route.action_type == "read"
    assert route.entity_type == "file"


def test_route_confidence_scoring_strong_match():
    router = IntentRouter()
    route = router.route("read the README.md file")
    assert route.entity_type == "file"
    assert route.action_type == "read"


def test_route_detects_git_entity():
    router = IntentRouter()
    route = router.route("show git commit history")
    assert route.entity_type == "git"


def test_route_detects_config_entity():
    router = IntentRouter()
    route = router.route("check the environment config")
    assert route.entity_type == "config"


def test_route_detects_command_entity():
    router = IntentRouter()
    route = router.route("run pytest in the terminal")
    assert route.entity_type == "command"


def test_route_detects_code_entity():
    router = IntentRouter()
    route = router.route("find the main function")
    assert route.entity_type == "code"


def test_score_keywords_returns_zero_on_empty_patterns():
    assert IntentRouter._score_keywords("anything", []) == 0.0


def test_score_keywords_returns_zero_on_no_matches():
    score = IntentRouter._score_keywords("hello world", ["foo", "bar"])
    assert score == 0.0


def test_score_keywords_returns_fraction_on_partial_match():
    score = IntentRouter._score_keywords("read the file", ["read", "write", "search"])
    assert score == pytest.approx(1 / 3)


def test_intent_to_mode_mapping():
    assert IntentRouter._intent_to_mode("profile") == "note_first"
    assert IntentRouter._intent_to_mode("factual") == "note_first"
    assert IntentRouter._intent_to_mode("temporal") == "episode_first"
    assert IntentRouter._intent_to_mode("constraint") == "hybrid"
    assert IntentRouter._intent_to_mode("procedural") == "hybrid"
    assert IntentRouter._intent_to_mode("unknown") == "hybrid"
