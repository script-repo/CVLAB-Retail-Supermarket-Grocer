"""FastAPI application entrypoint.

Serves the REST video API, the analysis WebSocket, a use-case catalogue
endpoint, and (optionally) the static Retail-Supermarket-Grocery-themed frontend.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import agent, analyze, gpu, streams, videos
from app.config import get_settings
from app.core.agent import get_agent_runtime
from app.usecases import list_usecases

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(videos.router)
app.include_router(analyze.router)
app.include_router(gpu.router)
app.include_router(agent.router)
app.include_router(streams.router)


@app.on_event("startup")
async def _start_agent() -> None:
    # Instantiate the agent runtime so its event-bus listener is registered
    # before the first analysis stream starts.
    get_agent_runtime()


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/usecases")
def usecases() -> dict:
    return {"usecases": list_usecases()}


# Serve the frontend if present (single-container deployment).
_frontend = Path(os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="frontend")
