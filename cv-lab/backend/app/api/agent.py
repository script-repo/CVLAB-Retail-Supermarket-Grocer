"""Agentic-ops API: live agent stream, state, snapshots, shift report.

``/ws/agent`` pushes typed JSON messages to the UI as they happen:
``event`` (CV detection/clearance), ``agent_run`` / ``agent_step`` /
``agent_done`` (the tool-use loop), ``workorder``, ``notification``.
On connect the client first receives an ``init`` message with full state so
late joiners render history.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.agent import get_agent_runtime
from app.core.events import get_event_bus
from app.core.llm import NaiError, get_nai_client

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    question: str


@router.get("/api/agent/state")
def agent_state() -> dict:
    return get_agent_runtime().state()


@router.get("/api/agent/ping")
async def agent_ping() -> dict:
    """Demo pre-flight: verifies the NAI endpoint answers."""
    ok = await get_nai_client().ping()
    s = get_agent_runtime().settings
    return {"ok": ok, "model": s.nai_model, "base_url": s.nai_base_url}


@router.get("/api/events/{event_id}/snapshot")
def event_snapshot(event_id: str) -> Response:
    jpeg = get_event_bus().snapshots.get(event_id)
    if not jpeg:
        raise HTTPException(404, "no snapshot for event")
    return Response(content=jpeg, media_type="image/jpeg")


@router.post("/api/agent/summary")
async def ops_summary() -> dict:
    """2-sentence NAI summary of the last 12h of store ops + 1 recommendation.
    Falls back to a deterministic, data-driven summary if NAI is unreachable."""
    return await get_agent_runtime().ops_summary()


@router.post("/api/agent/chat")
async def ops_chat(req: ChatRequest) -> dict:
    """Free-form natural-language question about the store, answered by NAI
    over the recent ops context (with a local fallback)."""
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    return await get_agent_runtime().answer_question(question)


@router.post("/api/agent/report")
async def shift_report() -> dict:
    try:
        report = await get_agent_runtime().shift_report()
    except NaiError as exc:
        raise HTTPException(502, f"NAI error: {exc}") from exc
    return {"report": report}


@router.websocket("/ws/agent")
async def agent_ws(ws: WebSocket) -> None:
    await ws.accept()
    runtime = get_agent_runtime()
    bus = get_event_bus()
    q = bus.subscribe()
    try:
        await ws.send_text(json.dumps({"type": "init", "state": runtime.state()}))
        while True:
            msg = await q.get()
            await ws.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("agent ws error")
    finally:
        bus.unsubscribe(q)
