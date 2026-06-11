"""Streaming analysis pipeline.

Decodes a stored video frame-by-frame with OpenCV, runs the selected use-case
analyzer, throttles to a target FPS, downscales, and JPEG-encodes each annotated
frame. Designed to be driven by the WebSocket layer: it yields (jpeg_bytes,
metrics) tuples and supports looping for a continuous "live" feel.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator

import cv2
import numpy as np

from app.config import get_settings
from app.core import perf
from app.core.storage import get_storage, video_key
from app.schemas import AnalysisConfig
from app.usecases import get_analyzer_cls


@dataclass
class FrameResult:
    jpeg: bytes
    metrics: dict
    frame_index: int
    timestamp_s: float


def _open_capture(video_id: str) -> cv2.VideoCapture:
    storage = get_storage()
    path = storage.get_path(video_key(video_id))
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video {video_id}")
    return cap


def _open_rtsp(url: str) -> cv2.VideoCapture:
    """Open an RTSP stream via FFmpeg. Transport/timeout come from the
    OPENCV_FFMPEG_CAPTURE_OPTIONS env (set on the deployment to use TCP)."""
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low: grab the latest frame
    except Exception:  # noqa: BLE001
        pass
    if not cap.isOpened():
        raise RuntimeError("Could not open RTSP stream")
    return cap


def grab_rtsp_frame(url: str) -> bytes:
    """Grab a single JPEG frame from an RTSP stream (for zone-drawing preview)."""
    cap = _open_rtsp(url)
    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("no frame received")
        frame = _downscale(frame, get_settings().max_stream_width)
        ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok2:
            raise RuntimeError("encode failed")
        return buf.tobytes()
    finally:
        cap.release()


def probe_video(video_id: str) -> dict:
    cap = _open_capture(video_id)
    try:
        return {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(cap.get(cv2.CAP_PROP_FPS) or 0),
            "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        }
    finally:
        cap.release()


def _downscale(frame: np.ndarray, max_w: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_w:
        return frame
    scale = max_w / w
    return cv2.resize(frame, (max_w, int(h * scale)), interpolation=cv2.INTER_AREA)


class AnalysisSession:
    """Owns one analyzer + capture for the lifetime of a WebSocket stream."""

    # RTSP reconnect tuning.
    _MAX_RECONNECT = 5
    _RECONNECT_BACKOFF_S = 1.0

    def __init__(self, config: AnalysisConfig):
        self.settings = get_settings()
        self.config = config
        self.is_rtsp = config.source == "rtsp"
        self.fps = config.fps or self.settings.target_fps

        if self.is_rtsp:
            self.cap = _open_rtsp(config.rtsp_url)
        else:
            self.cap = _open_capture(config.video_id)
        src_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or self.fps)
        self.src_fps = src_fps if src_fps > 0 else self.fps

        analyzer_cls = get_analyzer_cls(config.usecase)
        self.analyzer = analyzer_cls(fps=self.fps)

        ok, first = self.cap.read()
        if not ok:
            raise RuntimeError("Empty stream" if self.is_rtsp else "Empty video")
        first = _downscale(first, self.settings.max_stream_width)
        self.analyzer.setup(first, config)
        self._last_frame = first
        # Files can rewind for a clean start; live streams cannot seek.
        if not self.is_rtsp:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality]
        self._frame_index = 0
        self._start_t = time.monotonic()

    def update_params(self, params: dict) -> None:
        """Live tunable update (re-runs setup keeping the same capture)."""
        self.config.params.update(params)
        if self.is_rtsp:
            # No seeking on a live stream — re-run setup on the last frame.
            if self._last_frame is not None:
                self.analyzer.setup(self._last_frame, self.config)
            return
        pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, first = self.cap.read()
        if ok:
            first = _downscale(first, self.settings.max_stream_width)
            self.analyzer.setup(first, self.config)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, pos)

    def _reconnect(self) -> None:
        try:
            self.cap.release()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(self._RECONNECT_BACKOFF_S)
        self.cap = _open_rtsp(self.config.rtsp_url)

    def frames(self) -> Iterator[FrameResult]:
        """Generator yielding analyzed, JPEG-encoded frames at the target FPS."""
        interval = 1.0 / self.fps
        next_t = time.monotonic()
        reconnect_fails = 0
        while True:
            ok, frame = self.cap.read()
            if not ok:
                if self.is_rtsp:
                    reconnect_fails += 1
                    if reconnect_fails > self._MAX_RECONNECT:
                        raise RuntimeError("RTSP stream unreachable (max reconnects exceeded)")
                    self._reconnect()
                    continue
                if self.config.loop:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break
            reconnect_fails = 0

            frame = _downscale(frame, self.settings.max_stream_width)
            self._last_frame = frame
            # Live streams have no reliable frame index/fps — use wall clock.
            ts = (time.monotonic() - self._start_t) if self.is_rtsp else (self._frame_index / self.src_fps)
            t0 = time.perf_counter()
            annotated, metrics = self.analyzer.process_frame(frame, ts)
            perf.record(self.config.usecase, self.analyzer.title, time.perf_counter() - t0)
            ok2, buf = cv2.imencode(".jpg", annotated, self._encode_params)
            if not ok2:
                continue
            yield FrameResult(buf.tobytes(), metrics, self._frame_index, ts)
            self._frame_index += 1

            # Throttle to target FPS.
            next_t += interval
            sleep = next_t - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.monotonic()

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class PushAnalysisSession:
    """Analyzer driven by frames pushed from the browser (laptop camera).

    Mirrors ``AnalysisSession``'s analyzer/encode behavior but has no capture:
    the WebSocket layer hands it decoded frames via ``process()``. Analyzer
    setup is deferred to the first frame (needs real dimensions).
    """

    def __init__(self, config: AnalysisConfig):
        self.settings = get_settings()
        self.config = config
        self.fps = config.fps or self.settings.target_fps
        analyzer_cls = get_analyzer_cls(config.usecase)
        self.analyzer = analyzer_cls(fps=self.fps)
        self._encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.settings.jpeg_quality]
        self._frame_index = 0
        self._setup_done = False
        self._start_t: float | None = None
        self._last_frame: np.ndarray | None = None

    def process(self, frame_bgr: np.ndarray) -> FrameResult:
        frame = _downscale(frame_bgr, self.settings.max_stream_width)
        if not self._setup_done:
            self.analyzer.setup(frame, self.config)
            self._setup_done = True
            self._start_t = time.monotonic()
        self._last_frame = frame
        ts = time.monotonic() - (self._start_t or time.monotonic())
        t0 = time.perf_counter()
        annotated, metrics = self.analyzer.process_frame(frame, ts)
        perf.record(self.config.usecase, self.analyzer.title, time.perf_counter() - t0)
        ok, buf = cv2.imencode(".jpg", annotated, self._encode_params)
        if not ok:
            raise RuntimeError("JPEG encode failed")
        result = FrameResult(buf.tobytes(), metrics, self._frame_index, ts)
        self._frame_index += 1
        return result

    def update_params(self, params: dict) -> None:
        self.config.params.update(params)
        if self._last_frame is not None and self._setup_done:
            self.analyzer.setup(self._last_frame, self.config)

    def close(self) -> None:
        return None
