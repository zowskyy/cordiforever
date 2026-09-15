from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from web.sdk import create_session, get_session, list_sessions, remove_session


class SessionCreateRequest(BaseModel):
    workspace: str = "workspace"
    model: str = "gemma3:1b"
    profile: str = "lite"
    enable_semantic_router: bool = False
    db_path: str | None = None


class SessionResponse(BaseModel):
    id: str
    workspace: str
    model: str
    profile: str
    enable_semantic_router: bool


class MessageRequest(BaseModel):
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    for sid in list(list_sessions()):
        try:
            remove_session(sid)
        except Exception:
            pass


app = FastAPI(title="Cordi v2 Web", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session_api(body: SessionCreateRequest) -> SessionResponse:
    session = create_session(
        workspace=body.workspace,
        model=body.model,
        profile=body.profile,
        enable_semantic_router=body.enable_semantic_router,
        db_path=body.db_path,
    )
    await session.start()
    return SessionResponse(
        id=session.id,
        workspace=str(session.workspace),
        model=session.model,
        profile=session.profile,
        enable_semantic_router=session.enable_semantic_router,
    )


@app.get("/api/sessions")
async def list_sessions_api() -> dict[str, list[str]]:
    return {"sessions": list_sessions()}


@app.get("/api/sessions/{session_id}/events")
async def session_events(session_id: str) -> StreamingResponse:
    try:
        session = get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.ctx is None:
        raise HTTPException(status_code=400, detail="Session not started")

    async def event_stream() -> AsyncIterator[str]:
        while True:
            try:
                event = await asyncio.wait_for(session._event_queue.get(), timeout=2)
                payload = event.payload if hasattr(event, "payload") else {}
                yield f"data: {json.dumps({'type': event.type, 'data': payload})}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/sessions/{session_id}/message")
async def send_message(session_id: str, body: MessageRequest) -> dict[str, bool]:
    try:
        session = get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.ctx is None:
        raise HTTPException(status_code=400, detail="Session not started")
    asyncio.create_task(_consume_events(session, body.text))
    return {"ok": True}


async def _consume_events(session: AgentSession, text: str) -> None:
    async for _ in session.send_message(text):
        pass


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    try:
        remove_session(session_id)
    except KeyError:
        pass
    return {"ok": True}


@app.get("/api/files")
async def list_files(path: str = "workspace") -> dict[str, list[dict]]:
    root = Path(path).resolve()
    if not root.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    entries = []
    for entry in root.iterdir():
        entries.append({
            "name": entry.name,
            "path": str(entry),
            "kind": "dir" if entry.is_dir() else "file",
        })
    return {"files": sorted(entries, key=lambda e: (e["kind"] != "dir", e["name"]))}


@app.get("/api/files/content")
async def read_file(path: str) -> dict[str, str]:
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": file_path.read_text(encoding="utf-8", errors="replace")}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3080)
