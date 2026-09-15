from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.server import app
from web.sdk import get_session


@pytest.fixture()
def client():
    return TestClient(app)


def test_create_and_list_session(client):
    body = {
        "workspace": str(Path("workspace").resolve()),
        "model": "qwen2.5-coder:1.5b",
        "profile": "lite",
        "enable_semantic_router": False,
        "db_path": ":memory:",
    }
    create = client.post("/api/sessions", json=body)
    assert create.status_code == 200
    session = create.json()
    assert session["profile"] == "lite"
    assert session["model"] == "qwen2.5-coder:1.5b"

    listing = client.get("/api/sessions")
    assert listing.status_code == 200
    data = listing.json()
    assert session["id"] in data["sessions"]


def test_session_message_requires_started_session(client):
    bad_message = client.post("/api/sessions/does-not-exist/message", json={"text": "hi"})
    assert bad_message.status_code in (400, 404)


def test_session_events_endpoint_returns_streaming_response(client):
    body = {
        "workspace": str(Path("workspace").resolve()),
        "model": "qwen2.5-coder:1.5b",
        "profile": "lite",
        "enable_semantic_router": False,
        "db_path": ":memory:",
    }
    create = client.post("/api/sessions", json=body)
    assert create.status_code == 200
    session_id = create.json()["id"]

    session = get_session(session_id)
    session.ctx.events.emit("test.event", {"hello": "world"})

    response = client.get(f"/api/sessions/{session_id}/events", headers={"Accept": "text/event-stream"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_file_explorer_lists_workspace(client):
    response = client.get("/api/files", params={"path": str(Path("workspace").resolve())})
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert isinstance(data["files"], list)


def test_file_explorer_reads_file(client):
    target = Path("workspace").resolve() / "README.md"
    if not target.exists():
        pytest.skip("README.md not present in workspace")
    response = client.get("/api/files/content", params={"path": str(target)})
    assert response.status_code == 200
    data = response.json()
    assert "content" in data
    assert len(data["content"]) > 0
