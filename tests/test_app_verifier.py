"""Tests for the AppVerifier plugin.

AppVerifier is a deterministic, zero-token plugin that checks actual
filesystem artifacts against criteria derived from the user request.
It never calls the model or executes tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.context import Context
from core.plugin import Plugin
from core.registry import PluginRegistry
from plugins.agent.app_verifier import AppVerifier, VerificationCriterion, VerificationResult
from plugins.tools.file import FileTools


# ---------------------------------------------------------------------------
# Plugin structure & contract
# ---------------------------------------------------------------------------

def make_verifier(config=None):
    config = config or {"profile": "lite", "workspace": "/tmp"}
    ctx = Context(config=config)
    verifier = AppVerifier()
    verifier.register(ctx)
    return verifier


def test_app_verifier_is_plugin():
    verifier = make_verifier()
    assert isinstance(verifier, Plugin)
    assert AppVerifier.name == "app_verifier"


def test_app_verifier_has_no_terminal_dependency():
    """Verifier must only require file_tools and asgi_wsgi_tester, not terminal."""
    assert "file_tools" in AppVerifier.dependencies
    assert "asgi_wsgi_tester" in AppVerifier.dependencies
    assert "terminal" not in AppVerifier.dependencies


def test_app_verifier_health_check():
    """Health check must verify required capability methods exist."""
    verifier = make_verifier()
    health = verifier.health_check()
    assert health["healthy"] is True
    assert health["plugin"] == "app_verifier"
    assert health["capabilities"]["define_criteria"] is True
    assert health["capabilities"]["verify_completion"] is True
    assert health["capabilities"]["get_feedback"] is True


def test_app_verifier_contract_defined():
    """AppVerifier must declare __contract__ for plugin verification."""
    contract = AppVerifier.__contract__
    assert "version" in contract
    assert "provides" in contract
    assert "completion_verification" in contract["provides"]
    assert "feature_validation" in contract["provides"]
    assert contract["deterministic"] is True
    assert contract["zero_token"] is True


def test_app_verifier_resets_run_state():
    """Per-run state must reset between runs."""
    verifier = make_verifier()
    verifier._criteria = [VerificationCriterion("test", "desc", "file_exists", True, {"path": "a"})]
    verifier._results = [VerificationResult(verifier._criteria[0], False, "", "")]
    verifier.reset_run_state()
    assert verifier._criteria == []
    assert verifier._results == []


# ---------------------------------------------------------------------------
# Criteria definition — app pattern recognition
# ---------------------------------------------------------------------------

def test_define_criteria_todo_app():
    """Todo app requests should generate HTML + JS + add/delete criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build a todo app with add and delete", task_state)
    assert len(criteria) > 3
    names = [c.name for c in criteria]
    assert "todo_html_exists" in names
    assert "todo_js_exists" in names
    assert "todo_add_function" in names
    assert "todo_delete_ability" in names
    assert task_state["app_type"] == "todo"


def test_define_criteria_crud_app():
    """CRUD app requests should generate POST/GET/PUT/DELETE criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build a CRUD API with REST endpoints", task_state)
    names = [c.name for c in criteria]
    assert "crud_server_file" in names
    assert "crud_create_endpoint" in names
    assert "crud_read_endpoint" in names
    assert "crud_update_endpoint" in names
    assert "crud_delete_endpoint" in names
    assert task_state["app_type"] == "crud"


def test_define_criteria_calculator_app():
    """Calculator requests should generate display + buttons + operations criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build a calculator that can add and subtract", task_state)
    names = [c.name for c in criteria]
    assert "calc_html_exists" in names
    assert "calc_js_exists" in names
    assert "calc_display" in names
    assert "calc_number_buttons" in names
    assert "calc_operations" in names
    assert task_state["app_type"] == "calculator"


def test_define_criteria_dashboard_app():
    """Dashboard requests should generate container + visualization + data criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build a dashboard with charts and data", task_state)
    names = [c.name for c in criteria]
    assert "dashboard_html_exists" in names
    assert "dashboard_container" in names
    assert "dashboard_js_exists" in names
    assert "dashboard_data_source" in names
    assert task_state["app_type"] == "dashboard"


def test_define_criteria_generic_app():
    """Non-app requests should generate only generic criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("write hello to a file", task_state)
    assert task_state["app_type"] == "generic"
    # Should have some criteria (generic: no_placeholders is empty for generic)
    assert isinstance(criteria, list)


@pytest.mark.parametrize("request_text", [
    "Read notes.txt, then write a file summary.txt containing only the number of lines in notes.txt.",
    "Fix the error message in app.py",
    "Explain how the account total is computed in billing.py",
    "Refactor the token parser in lexer.py",
])
def test_define_criteria_does_not_grade_ordinary_coding_tasks_as_apps(request_text):
    verifier = make_verifier()
    task_state = {}
    verifier.define_criteria(request_text, task_state)
    assert task_state["app_type"] == "generic"


def test_define_criteria_keyword_matching_is_whole_word():
    verifier = make_verifier()
    task_state = {}
    verifier.define_criteria("create a summary page for rapid prototyping", task_state)
    assert task_state["app_type"] == "generic"
    verifier.define_criteria("build a calculator with totals", task_state)
    assert task_state["app_type"] == "calculator"


def test_define_criteria_auth_app():
    """Auth app requests should generate login/signup/session criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build an auth app with login and signup", task_state)
    names = [c.name for c in criteria]
    assert "auth_server_file" in names
    assert "auth_login_endpoint" in names
    assert "auth_signup_endpoint" in names
    assert "auth_session_management" in names
    assert task_state["app_type"] == "auth"


def test_define_criteria_ecommerce_app():
    """E-commerce app requests should generate product/cart/checkout criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build an e-commerce store with cart and checkout", task_state)
    names = [c.name for c in criteria]
    assert "ecommerce_html_exists" in names
    assert "ecommerce_product_list" in names
    assert "ecommerce_cart_functionality" in names
    assert "ecommerce_checkout" in names
    assert task_state["app_type"] == "ecommerce"


def test_define_criteria_chat_app():
    """Chat app requests should generate message/send/realtime criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build a chat app with real-time messaging", task_state)
    names = [c.name for c in criteria]
    assert "chat_html_exists" in names
    assert "chat_message_list" in names
    assert "chat_send_functionality" in names
    assert "chat_realtime" in names
    assert task_state["app_type"] == "chat"


def test_define_criteria_dataviz_app():
    """Data visualization requests should generate chart/data criteria."""
    verifier = make_verifier()
    task_state = {}
    criteria = verifier.define_criteria("build a data visualization with charts and graphs", task_state)
    names = [c.name for c in criteria]
    assert "dataviz_html_exists" in names
    assert "dataviz_chart_library" in names
    assert "dataviz_data_source" in names
    assert task_state["app_type"] == "dataviz"


# ---------------------------------------------------------------------------
# File existence checks
# ---------------------------------------------------------------------------

def test_verify_file_exists_pass(tmp_path):
    """Existing files should pass file_exists check."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    task_state = {"app_type": "todo"}
    criterion = VerificationCriterion(
        "todo_html_exists", "Must have HTML", "file_exists", True, {"path": "index.html"}
    )
    verifier._criteria = [criterion]
    result = verifier._check_criterion(criterion, tmp_path)
    assert result.passed is True


def test_verify_file_exists_fail(tmp_path):
    """Missing files should fail file_exists check."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    task_state = {"app_type": "todo"}
    criterion = VerificationCriterion(
        "todo_html_exists", "Must have HTML", "file_exists", True, {"path": "index.html"}
    )
    verifier._criteria = [criterion]
    result = verifier._check_criterion(criterion, tmp_path)
    assert result.passed is False
    assert "does not exist" in result.feedback.lower()


# ---------------------------------------------------------------------------
# File content checks
# ---------------------------------------------------------------------------

def test_verify_file_content_pass(tmp_path):
    """Files with all required patterns should pass."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "app.js").write_text("function add() { return filtered; }", encoding="utf-8")
    criterion = VerificationCriterion(
        "todo_add_function", "Must have add function", "file_content", True,
        {"path": "app.js", "patterns": ["function", "add"]}
    )
    result = verifier._check_criterion(criterion, tmp_path)
    assert result.passed is True


def test_verify_file_content_fail(tmp_path):
    """Files missing required patterns should fail."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "app.js").write_text("const x = 1;", encoding="utf-8")
    criterion = VerificationCriterion(
        "todo_add_function", "Must have add function", "file_content", True,
        {"path": "app.js", "patterns": ["function", "add"]}
    )
    result = verifier._check_criterion(criterion, tmp_path)
    assert result.passed is False
    assert "missing" in result.feedback.lower()


def test_verify_file_content_multiple_patterns(tmp_path):
    """All patterns must be present, not just some."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "app.js").write_text("const result = items.filter(x => x);", encoding="utf-8")
    criterion = VerificationCriterion(
        "check_ops", "Must have operations", "file_content", True,
        {"path": "app.js", "patterns": ["+", "-", "*", "/"]}
    )
    result = verifier._check_criterion(criterion, tmp_path)
    # Missing *, /, +
    assert result.passed is False
    assert "missing" in result.feedback.lower()


# ---------------------------------------------------------------------------
# Feedback generation
# ---------------------------------------------------------------------------

def test_feedback_lists_all_failures(tmp_path):
    """Feedback should list every failed criterion."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    task_state = {"app_type": "todo"}
    verifier.define_criteria("build a todo app", task_state)
    verifier.verify_completion(str(tmp_path), task_state)
    # No files exist → all criteria fail
    feedback = verifier.get_feedback()
    assert "failed" in feedback.lower()
    assert len(feedback) > 10  # Non-trivial feedback


def test_feedback_empty_when_all_pass(tmp_path):
    """Feedback should indicate success when all criteria pass."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    # Create minimal todo app files
    (tmp_path / "index.html").write_text("<ul id='list'><!-- todo list --></ul>", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "function add() {} const items = []; items.filter(x => x); items.splice(0,1);",
        encoding="utf-8"
    )
    task_state = {"app_type": "todo"}
    verifier.define_criteria("build a todo app", task_state)
    verifier.verify_completion(str(tmp_path), task_state)
    feedback = verifier.get_feedback()
    assert "passed" in feedback.lower()


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def test_verify_completion_no_criteria_passes():
    """When no criteria are defined, completion should be vacuously true."""
    verifier = make_verifier()
    result = verifier.verify_completion("/tmp", {})
    assert result is True


def test_verify_completion_all_required_pass(tmp_path):
    """When all required criteria pass, completion returns True."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "app.js").write_text("function add() {} const items = []; items.filter(x => x); items.splice(0,1);", encoding="utf-8")
    (tmp_path / "index.html").write_text("<ul id='list'>todo</ul>", encoding="utf-8")
    task_state = {"app_type": "todo"}
    verifier.define_criteria("build a todo app", task_state)
    result = verifier.verify_completion(str(tmp_path), task_state)
    assert result is True


def test_verify_completion_required_fails(tmp_path):
    """When any required criterion fails, completion returns False."""
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "app.js").write_text("function add() {}", encoding="utf-8")
    # Missing index.html
    task_state = {"app_type": "todo"}
    verifier.define_criteria("build a todo app", task_state)
    result = verifier.verify_completion(str(tmp_path), task_state)
    assert result is False


# ---------------------------------------------------------------------------
# Integration with registry (minimal)
# ---------------------------------------------------------------------------

def test_app_verifier_registered_with_file_tools(tmp_path):
    """AppVerifier should register successfully when file_tools and asgi_wsgi_tester are available."""
    from core.context import Context
    from core.registry import PluginRegistry
    from plugins.tools.asgi_wsgi_tester import ASGIWSGITester

    ctx = Context(config={"profile": "lite", "workspace": str(tmp_path)})
    reg = PluginRegistry(ctx)
    reg.register(FileTools(tmp_path))
    reg.register(ASGIWSGITester())
    reg.register(AppVerifier())
    assert "app_verifier" in ctx.plugins


def _make_verifier_with_server_tester(config=None):
    """Create verifier with ASGIWSGITester registered."""
    from plugins.tools.asgi_wsgi_tester import ASGIWSGITester

    config = config or {"profile": "lite", "workspace": "/tmp"}
    ctx = Context(config=config)
    reg = PluginRegistry(ctx)
    reg.register(FileTools(Path("/tmp")))
    reg.register(ASGIWSGITester())
    verifier = AppVerifier()
    verifier.register(ctx)
    # Manually set _server_tester since register happens before all plugins start
    verifier._server_tester = ctx.plugins.get("asgi_wsgi_tester")
    return verifier


def test_server_runs_check_without_tester():
    """Server runs check should fail gracefully when tester is None."""
    verifier = make_verifier()
    criterion = VerificationCriterion(
        name="test_server",
        description="Server must run",
        check_type="server_runs",
        parameters={"command": "python server.py"},
    )
    result = verifier._check_server_runs(criterion, Path("/tmp"), criterion.parameters)
    assert result.passed is False
    assert "not available" in result.feedback or "requires" in result.feedback


def test_verifier_with_server_tester_available():
    """Test that verifier properly detects and delegates to ASGIWSGITester."""
    verifier = _make_verifier_with_server_tester()
    assert verifier._server_tester is not None
    assert verifier._server_tester.name == "asgi_wsgi_tester"


def test_server_runs_check_with_mock_tester():
    """Server runs check should work with a mock tester."""
    verifier = make_verifier()
    mock_tester = MagicMock()
    mock_tester.start_server.return_value = True
    mock_tester.test_endpoints.return_value = {
        "passed": True,
        "summary": "4/4 endpoints passed",
    }
    verifier._server_tester = mock_tester

    criterion = VerificationCriterion(
        name="test_server",
        description="Server must run",
        check_type="server_runs",
        parameters={
            "command": "python server.py",
            "base_url": "http://127.0.0.1:8000",
            "endpoints": [
                {"method": "GET", "path": "/api/items", "expected_status": 200},
            ],
        },
    )
    result = verifier._check_server_runs(criterion, Path("/tmp"), criterion.parameters)
    assert result.passed is True
    mock_tester.start_server.assert_called_once()
    mock_tester.test_endpoints.assert_called_once()
    mock_tester.stop_server.assert_called_once()


def test_server_runs_check_server_fails():
    """Server runs check should fail when server doesn't start."""
    verifier = make_verifier()
    mock_tester = MagicMock()
    mock_tester.start_server.return_value = False
    verifier._server_tester = mock_tester

    criterion = VerificationCriterion(
        name="test_server",
        description="Server must run",
        check_type="server_runs",
        parameters={"command": "python server.py"},
    )
    result = verifier._check_server_runs(criterion, Path("/tmp"), criterion.parameters)
    assert result.passed is False
    assert "failed to start" in result.feedback.lower() or "did not start" in result.feedback.lower()
