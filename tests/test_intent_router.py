from __future__ import annotations

import tempfile
from pathlib import Path

from core.intent_router import IntentRouter


def test_route_detects_goal_scope_project_wide():
    router = IntentRouter()
    route = router.route("Fix all files in the project")
    assert route.goal_scope == "project_wide"


def test_route_detects_goal_scope_single_file():
    router = IntentRouter()
    route = router.route("Fix this file")
    assert route.goal_scope == "single_file"


def test_route_detects_action_type_read():
    router = IntentRouter()
    route = router.route("Show me the config")
    assert route.action_type == "read"


def test_route_detects_action_type_write():
    router = IntentRouter()
    route = router.route("Create a new Python script")
    assert route.action_type == "write"


def test_route_detects_action_type_search():
    router = IntentRouter()
    route = router.route("Find all references to main")
    assert route.action_type == "search"


def test_route_detects_action_type_execute():
    router = IntentRouter()
    route = router.route("Run the test suite")
    assert route.action_type == "execute"


def test_route_detects_action_type_analyze():
    router = IntentRouter()
    route = router.route("Analyze the code structure")
    assert route.action_type == "analyze"


def test_route_detects_entity_type_file():
    router = IntentRouter()
    route = router.route("Read the README.md file")
    assert route.entity_type == "file"


def test_route_detects_entity_type_code():
    router = IntentRouter()
    route = router.route("Find the main function")
    assert route.entity_type == "code"


def test_route_detects_entity_type_command():
    router = IntentRouter()
    route = router.route("Run pytest in the terminal")
    assert route.entity_type == "command"


def test_route_detects_entity_type_git():
    router = IntentRouter()
    route = router.route("Show git commit history")
    assert route.entity_type == "git"


def test_route_detects_entity_type_config():
    router = IntentRouter()
    route = router.route("Check the environment config")
    assert route.entity_type == "config"
