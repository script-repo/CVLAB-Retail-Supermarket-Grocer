"""Network stream helper endpoints.

A single-frame preview used by the UI to draw zones / set the stage aspect
ratio before starting a stream analysis (the equivalent of a video thumbnail).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.core.pipeline import grab_rtsp_frame

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rtsp", tags=["rtsp"])


@router.get("/preview")
async def rtsp_preview(url: str = Query(..., description="RTSP or HTTP(S) MJPEG stream URL")) -> Response:
    if not url.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
        raise HTTPException(400, "URL must start with rtsp://, rtsps://, http://, or https://")
    import asyncio

    loop = asyncio.get_running_loop()
    try:
        # Bounded so an unreachable URL fails fast (FFmpeg honors stimeout via
        # OPENCV_FFMPEG_CAPTURE_OPTIONS; this is a hard backstop).
        jpeg = await asyncio.wait_for(loop.run_in_executor(None, grab_rtsp_frame, url), timeout=12)
    except asyncio.TimeoutError:
        raise HTTPException(504, "Stream preview timed out (stream unreachable?)")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Could not read network stream: {exc}")
    return Response(content=jpeg, media_type="image/jpeg")
