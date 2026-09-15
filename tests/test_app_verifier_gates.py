from __future__ import annotations

from pathlib import Path

import pytest

from plugins.agent.app_verifier import AppVerifier, GateResult, VerificationCriterion


def make_verifier(config=None):
    config = config or {"profile": "lite", "workspace": "/tmp"}
    from core.context import Context
    ctx = Context(config=config)
    verifier = AppVerifier()
    verifier.register(ctx)
    return verifier


def test_gate_result_dataclass():
    gate = GateResult(gate="file_exists", passed=True, findings=["ok"], score=1.0, metadata={"x": 1})
    assert gate.gate == "file_exists"
    assert gate.passed is True
    assert gate.findings == ["ok"]
    assert gate.score == 1.0
    assert gate.metadata == {"x": 1}


def test_app_verifier_gate_caching(tmp_path):
    verifier = make_verifier({"workspace": str(tmp_path)})
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    criterion = VerificationCriterion("test", "desc", "file_exists", True, {"path": "index.html"})
    verifier._criteria = [criterion]
    result1 = verifier._check_criterion(criterion, tmp_path)
    result2 = verifier._check_criterion(criterion, tmp_path)
    assert result1.passed is True
    assert result2.passed is True
    # Cache should have been used on second call
    assert len(verifier._gate_cache) == 1


def test_app_verifier_gate_file_exists():
    verifier = make_verifier()
    criterion = VerificationCriterion("test", "desc", "file_exists", True, {"path": "missing.txt"})
    result = verifier._check_criterion(criterion, Path("/tmp"))
    assert result.passed is False
    assert "does not exist" in result.feedback.lower()


def test_app_verifier_gate_file_content():
    verifier = make_verifier()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "app.js").write_text("function add() {}", encoding="utf-8")
        criterion = VerificationCriterion("test", "desc", "file_content", True, {"path": "app.js", "patterns": ["function"]})
        result = verifier._check_criterion(criterion, ws)
        assert result.passed is True


def test_app_verifier_gate_no_placeholders():
    verifier = make_verifier()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "index.html").write_text("<html>TODO: fix this</html>", encoding="utf-8")
        criterion = VerificationCriterion("test", "desc", "no_placeholders", True, {"path": "index.html"})
        result = verifier._check_criterion(criterion, ws)
        assert result.passed is False


def test_app_verifier_gate_schema_valid():
    verifier = make_verifier()
    criterion = VerificationCriterion("test", "desc", "schema_valid", True, {"path": "schema.json"})
    result = verifier._check_criterion(criterion, Path("/tmp"))
    assert result.passed is False
    assert "unknown" in result.feedback.lower()


def test_app_verifier_reset_clears_cache():
    verifier = make_verifier()
    verifier._gate_cache = {"key": "value"}
    verifier.reset_run_state()
    assert verifier._gate_cache == {}
