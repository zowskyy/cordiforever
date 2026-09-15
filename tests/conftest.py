from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run integration tests that invoke the real 1.5B Ollama model (slow, flaky). Off by default.",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "fast: deterministic; no 1.5B model invocation (default gate).")
    config.addinivalue_line(
        "markers",
        "integration: requires the real 1.5B Ollama model; auto-skipped unless --live.",
    )


def pytest_collection_modifyitems(config, items):
    """Fast/slow split (first-principles): never let a 1.5B live test block the green gate."""
    if config.getoption("--live"):
        return
    skip_integration = pytest.mark.skip(reason="Ollama-1.5B integration test; pass --live to enable.")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
