"""Web UI dashboard plugin for Cordi v2.

Serves a single-page dashboard at ``http://127.0.0.1:3080`` with:
- Session list and management
- Live event stream (Server-Sent Events)
- Metrics overview
- Basic agent interaction

The plugin is zero-token and deterministic. It only uses the existing
event log and metrics plugins; no LLM calls are made.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Optional

from core.plugin import Plugin
from core.events import Event

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    _FASTAPI_AVAILABLE = True
    try:
        from sse_starlette.sse import EventSourceResponse
        _SSE_AVAILABLE = True
    except ImportError:  # pragma: no cover - optional dependency
        _SSE_AVAILABLE = False
except ImportError:  # pragma: no cover - optional dependency
    _FASTAPI_AVAILABLE = False
    _SSE_AVAILABLE = False


if _FASTAPI_AVAILABLE:
    api = FastAPI()
    api.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @api.get("/")
    async def root() -> HTMLResponse:
        template_path = Path(__file__).parent / "templates" / "index.html"
        if template_path.exists():
            return HTMLResponse(template_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Continuity Kernel Dashboard</h1><p>Template not found</p>", status_code=200)

    @api.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "fastapi": True}

    @api.get("/api/sessions")
    async def list_sessions(request: Request) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.list_sessions())

    @api.get("/api/sessions/{session_id}")
    async def get_session(session_id: str, request: Request) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.get_session(session_id))

    @api.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.delete_session(session_id))

    @api.post("/api/sessions/{session_id}/run")
    async def run_session(session_id: str, request: Request, body: dict[str, Any]) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.run_session(session_id, body.get("input", "")))

    @api.get("/api/sessions/{session_id}/events")
    async def stream_events(session_id: str, request: Request):
        web = request.app.state.web_plugin
        stop_event = asyncio.Event()
        return EventSourceResponse(web.stream_events(session_id, stop_event))

    @api.get("/api/metrics")
    async def get_metrics(request: Request) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.get_metrics())

    @api.get("/api/models")
    async def list_models(request: Request) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.list_models())

    @api.post("/api/models/{model_id}/switch")
    async def switch_model(model_id: str, request: Request, body: dict[str, Any]) -> JSONResponse:
        web = request.app.state.web_plugin
        return JSONResponse(web.switch_model(model_id, body))


class WebDashboard(Plugin):
    """Zero-token FastAPI web dashboard for local model interaction."""

    name = "web_dashboard"
    dependencies = ("event_logger",)
    _HOST = "127.0.0.1"
    _PORT = 3080

    def __init__(self) -> None:
        super().__init__()
        self._thread: Optional[threading.Thread] = None
        self._server: Any = None
        self._uvicorn_server: Any = None

    def start(self) -> None:
        if not _FASTAPI_AVAILABLE:
            return
        if getattr(self, "_started", False):
            return
        self._started = True
        self._server = api
        self._server.state.web_plugin = self
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        self._thread = thread

    def stop(self) -> None:
        self._started = False
        if self._uvicorn_server is not None:
            try:
                self._uvicorn_server.shutdown()
            except Exception:
                pass
            self._uvicorn_server = None
        self._server = None
        self._thread = None

    def _run(self) -> None:
        import uvicorn
        config = uvicorn.Config(self._server, host=self._HOST, port=self._PORT, log_level="warning")
        self._uvicorn_server = uvicorn.Server(config)
        self._uvicorn_server.run()

    def list_sessions(self) -> list[dict[str, Any]]:
        event_logger = self.context.plugins.get("event_logger") if self.context else None
        if event_logger is None or not hasattr(event_logger, "_event_log"):
            return []
        try:
            rows = event_logger._event_log.query("SELECT DISTINCT session_id FROM events ORDER BY session_id")
            return [{"session_id": row[0]} for row in rows]
        except Exception:
            return []

    def get_session(self, session_id: str) -> dict[str, Any]:
        event_logger = self.context.plugins.get("event_logger") if self.context else None
        if event_logger is None or not hasattr(event_logger, "_event_log"):
            return {"session_id": session_id, "events": []}
        try:
            rows = event_logger._event_log.get_session_events(session_id)
            return {
                "session_id": session_id,
                "events": [
                    {
                        "id": r.id,
                        "timestamp": r.timestamp,
                        "type": r.type,
                        "payload": r.payload,
                    }
                    for r in rows
                ],
            }
        except Exception:
            return {"session_id": session_id, "events": []}

    def delete_session(self, session_id: str) -> dict[str, Any]:
        self._emit("session.deleted", {"session_id": session_id})
        return {"deleted": True, "session_id": session_id}

    def run_session(self, session_id: str, user_input: str) -> dict[str, Any]:
        agent = self.context.plugins.get("agent_loop") if self.context else None
        if agent is None:
            return {"error": "agent_loop not available"}
        try:
            result = agent.run(user_input)
            return {"session_id": session_id, "result": result}
        except Exception as exc:
            return {"session_id": session_id, "error": str(exc)}

    def stream_events(self, session_id: str, stop_event: Any) -> Any:
        event_logger = self.context.plugins.get("event_logger") if self.context else None
        if event_logger is None or not hasattr(event_logger, "_event_log"):
            return
        last_id = 0
        while not stop_event.is_set():
            try:
                rows = event_logger._event_log.get_events_after(session_id, last_id)
                for row in rows:
                    last_id = row.id or last_id
                    payload = {
                        "id": row.id,
                        "timestamp": row.timestamp,
                        "type": row.type,
                        "payload": row.payload,
                    }
                    yield {"event": "message", "data": json.dumps(payload)}
            except Exception:
                pass
            stop_event.wait(0.5)

    def get_metrics(self) -> dict[str, Any]:
        metrics = self.context.plugins.get("metrics") if self.context else None
        if metrics is None:
            return {}
        try:
            return metrics.get_metrics()
        except Exception:
            return {}

    def list_models(self) -> list[dict[str, Any]]:
        model = self.context.plugins.get("ollama_model") if self.context else None
        if model is None:
            return []
        try:
            return [{"id": getattr(model, "model", "unknown"), "provider": "ollama"}]
        except Exception:
            return []

    def switch_model(self, model_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self._emit("tools.change", {"model": model_id})
        return {"switched": True, "model": model_id}

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.context is None:
            return
        try:
            self.context.events.emit(event_type, payload)
        except Exception:
            pass
