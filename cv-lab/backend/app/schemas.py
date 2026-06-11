"""Pydantic schemas shared across the API and WebSocket layers."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class VideoMeta(BaseModel):
    """Metadata persisted alongside an uploaded video."""

    id: str
    filename: str
    content_type: str = "video/mp4"
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frame_count: int = 0
    duration_s: float = 0.0
    created_at: str
    thumb_url: str | None = None


class VideoList(BaseModel):
    videos: list[VideoMeta]


# --- Zones / config sent from the browser to drive an analysis -------------

class Polygon(BaseModel):
    """A normalized polygon (coords in 0..1 relative to frame width/height)."""

    name: str = "zone"
    points: list[tuple[float, float]] = Field(default_factory=list)


class AnalysisConfig(BaseModel):
    usecase: str
    # Where frames come from:
    #   video  -> stored file pulled by the server (default, back-compatible)
    #   camera -> browser webcam, frames pushed over the WebSocket as JPEGs
    #   rtsp   -> network stream pulled by the server via OpenCV/FFmpeg
    #             (RTSP plus HTTP/HTTPS MJPEG streams)
    source: Literal["video", "camera", "rtsp"] = "video"
    video_id: str | None = None
    rtsp_url: str | None = None
    zones: list[Polygon] = Field(default_factory=list)
    # Per-use-case tunables (occupancy threshold, queue limit, etc.)
    params: dict[str, Any] = Field(default_factory=dict)
    loop: bool = True
    # Optional per-stream FPS override (multi-view runs tiles at reduced rate).
    fps: int | None = Field(default=None, ge=1, le=30)

    @model_validator(mode="after")
    def _check_source(self) -> "AnalysisConfig":
        if self.source == "video" and not self.video_id:
            raise ValueError("video_id is required when source='video'")
        if self.source == "rtsp":
            if not self.rtsp_url:
                raise ValueError("rtsp_url is required when source='rtsp'")
            if not self.rtsp_url.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
                raise ValueError("rtsp_url must start with rtsp://, rtsps://, http://, or https://")
        return self


# --- WebSocket control messages (client -> server) -------------------------

class ControlMessage(BaseModel):
    action: Literal["start", "pause", "resume", "stop", "config"]
    config: AnalysisConfig | None = None
    params: dict[str, Any] | None = None


# --- Metric event (server -> client), sent as JSON next to each JPEG -------

class MetricEvent(BaseModel):
    type: Literal["metrics"] = "metrics"
    usecase: str
    frame_index: int
    timestamp_s: float
    status: Literal["ok", "alert"] = "ok"
    headline: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
