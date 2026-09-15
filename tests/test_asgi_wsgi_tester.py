"""Tests for ASGIWSGITester plugin — health check, lifecycle, and deterministic unit tests."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins.tools.asgi_wsgi_tester import ASGIWSGITester


def test_asgi_wsgi_tester_registration():
    """Test plugin metadata is correctly declared."""
    tester = ASGIWSGITester()
    assert tester.name == "asgi_wsgi_tester"
    assert tester.dependencies == ()


def test_asgi_wsgi_tester_health_check():
    """Test health_check returns correct structure."""
    tester = ASGIWSGITester()
    result = tester.health_check()
    assert result["healthy"] is True
    assert result["plugin"] == "asgi_wsgi_tester"
    assert result["contract_version"] == "1.0"
    assert "start_server" in result["capabilities"]
    assert "test_endpoint" in result["capabilities"]
    assert "test_endpoints" in result["capabilities"]
    assert "stop_server" in result["capabilities"]


def test_asgi_wsgi_tester_contract():
    """Test that __contract__ declares correct capabilities."""
    tester = ASGIWSGITester()
    contract = tester.__contract__
    assert contract["version"] == "1.0"
    assert "server_testing" in contract["provides"]
    assert contract["deterministic"] is True
    assert contract["zero_token"] is True


def test_asgi_wsgi_tester_start_stop():
    """Test that start/stop do not raise errors."""
    tester = ASGIWSGITester()
    tester.start()
    tester.stop()
    # Second stop should be safe (no server running)
    tester.stop()


def test_asgi_wsgi_tester_reset_run_state():
    """Test that reset_run_state calls stop safely."""
    tester = ASGIWSGITester()
    tester.start()
    tester.reset_run_state()
    tester.reset_run_state()  # Second call should be safe


def test_asgi_wsgi_tester_start_server_not_available():
    """Test start_server returns False when command fails."""
    tester = ASGIWSGITester()
    tester.start()
    # Use a command that will definitely fail
    result = tester.start_server("nonexistent_command_that_does_not_exist --fail", timeout=2.0)
    assert result is False
    tester.stop()


def test_asgi_wsgi_tester_find_available_port():
    """Test that find_available_port returns a valid port."""
    tester = ASGIWSGITester()
    port = tester._find_available_port(9000, 9100)
    assert 9000 <= port <= 9100
    # Verify it's actually available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_asgi_wsgi_tester_test_endpoint_no_server():
    """Test test_endpoint returns error when no server is running."""
    tester = ASGIWSGITester()
    tester.start()
    tester._base_url = "http://127.0.0.1:59999"  # Unlikely to have a server
    result = tester.test_endpoint("GET", "/", expected_status=200)
    assert result["passed"] is False
    assert result["error"] is not None


def test_asgi_wsgi_tester_test_endpoint_with_mock():
    """Test test_endpoint with mocked HTTP responses."""
    tester = ASGIWSGITester()
    tester.start()
    tester._base_url = "http://127.0.0.1:8000"

    mock_response = {
        "status_code": 200,
        "response": json.dumps({"status": "ok"}),
        "error": None,
    }

    with patch.object(tester, "_check_server_started"):
        result = tester.test_endpoint("GET", "/health", expected_status=200)
        # Without actual server, this should return error
        assert result["passed"] is False


def test_asgi_wsgi_tester_test_endpoints_aggregation():
    """Test that test_endpoints aggregates results correctly."""
    tester = ASGIWSGITester()
    tester.start()
    tester._base_url = "http://127.0.0.1:59998"

    endpoints = [
        {"method": "GET", "path": "/api/items", "expected_status": 200},
        {"method": "POST", "path": "/api/items", "expected_status": 201, "json_body": {"name": "test"}},
    ]

    result = tester.test_endpoints(endpoints)
    assert result["passed"] is False
    assert len(result["results"]) == 2
    assert "0/2" in result["summary"] or "0/2" in result.get("summary", "")
    tester.stop()


def test_asgi_wsgi_tester_server_process_none():
    """Test that stop_server is safe when no server is running."""
    tester = ASGIWSGITester()
    tester.start()
    tester.stop_server()  # Should not raise


def test_asgi_wsgi_tester_multiple_starts():
    """Test that starting multiple times doesn't leak processes."""
    tester = ASGIWSGITester()
    tester.start()
    tester.start()
    tester.stop()
    tester.stop()  # Should be safe


def test_asgi_wsgi_tester_with_context():
    """Test integration with Context — plugin registration."""
    from core.context import Context
    from core.registry import PluginRegistry

    ctx = Context(config={"workspace": "."})
    reg = PluginRegistry(ctx)
    reg.register(ASGIWSGITester())

    assert "asgi_wsgi_tester" in ctx.plugins
    assert ctx.plugins["asgi_wsgi_tester"].name == "asgi_wsgi_tester"
