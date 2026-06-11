"""WebSocket endpoint that streams annotated frames + metrics.

Protocol
--------
Client connects to ``/ws/analyze`` and sends a JSON control message::

    {"action": "start", "config": {"source": "video", "video_id": "...",
                                    "usecase": "uc-06", "zones": [...], ...}}

``config.source`` selects the frame source:
  - ``video`` : server pulls a stored file (default).
  - ``rtsp``  : server pulls a network stream (``rtsp_url``).
  - ``camera``: the browser pushes JPEG frames as **binary** WebSocket messages;
                each binary message is one camera frame to analyze.

The server then streams, per analyzed frame:
  1. a binary message: JPEG bytes of the annotated frame
  2. a text message: JSON metrics for that frame

Further control messages are accepted at any time:
  {"action": "pause" | "resume" | "stop"}
  {"action": "config", "params": {...}}   # live-tune thresholds
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import StreamMonitor
from app.core.pipeline import AnalysisSession, PushAnalysisSession
from app.schemas import AnalysisConfig

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/analyze")
async def analyze_ws(ws: WebSocket) -> None:
    await ws.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)          # outbound (annotated frames)
    inbound: asyncio.Queue = asyncio.Queue(maxsize=1)        # camera frames (drop-old)

    pause_event = threading.Event()
    pause_event.set()  # start un-paused
    stop_event = threading.Event()
    params_lock = threading.Lock()
    pending_params: dict = {}

    session = None                  # AnalysisSession | PushAnalysisSession | None
    monitor: StreamMonitor | None = None

    def _enqueue(item) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # Drop the oldest to stay "live".
            try:
                queue.get_nowait()
                queue.put_nowait(item)
            except Exception:  # noqa: BLE001
                pass

    # --- pull worker (video / rtsp): reads frames from the server-side capture ---
    def worker() -> None:
        nonlocal pending_params
        try:
            for fr in session.frames():
                if stop_event.is_set():
                    break
                while not pause_event.is_set() and not stop_event.is_set():
                    threading.Event().wait(0.05)
                if stop_event.is_set():
                    break
                with params_lock:
                    if pending_params:
                        session.update_params(pending_params)
                        pending_params = {}
                loop.call_soon_threadsafe(_enqueue, fr)
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker error")
            loop.call_soon_threadsafe(_enqueue, ("__error__", str(exc)))
        finally:
            loop.call_soon_threadsafe(_enqueue, None)  # sentinel: stream ended

    # --- push worker (camera): processes frames pushed from the browser ---
    async def camera_worker(psession: PushAnalysisSession) -> None:
        nonlocal pending_params
        try:
            while not stop_event.is_set():
                frame = await inbound.get()
                if frame is None:
                    break
                while not pause_event.is_set() and not stop_event.is_set():
                    await asyncio.sleep(0.05)
                if stop_event.is_set():
                    break
                with params_lock:
                    if pending_params:
                        psession.update_params(pending_params)
                        pending_params = {}
                try:
                    fr = await loop.run_in_executor(None, psession.process, frame)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("camera worker error")
                    _enqueue(("__error__", str(exc)))
                    break
                _enqueue(fr)
        finally:
            _enqueue(None)

    async def sender() -> None:
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, tuple) and item and item[0] == "__error__":
                await ws.send_text(json.dumps({"type": "error", "message": item[1]}))
                break
            await ws.send_bytes(item.jpeg)
            await ws.send_text(json.dumps({
                "type": "metrics",
                "usecase": session.config.usecase,
                "frame_index": item.frame_index,
                "timestamp_s": round(item.timestamp_s, 2),
                **item.metrics,
            }))
            # Feed the agentic layer: sustained status transitions become events.
            if monitor:
                await monitor.feed(item.metrics, item.jpeg)

    worker_thread: threading.Thread | None = None
    camera_task: asyncio.Task | None = None
    sender_task: asyncio.Task | None = None

    def _push_inbound(jpeg_bytes: bytes) -> None:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return
        try:
            inbound.put_nowait(img)
        except asyncio.QueueFull:
            # Drop the oldest pending frame to stay live.
            try:
                inbound.get_nowait()
                inbound.put_nowait(img)
            except Exception:  # noqa: BLE001
                pass

    async def _teardown_run() -> None:
        """Stop any in-flight worker/task before (re)starting."""
        stop_event.set()
        if camera_task:
            inbound.put_nowait(None) if not inbound.full() else None
            try:
                await asyncio.wait_for(camera_task, timeout=2)
            except Exception:  # noqa: BLE001
                pass
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=2)
        if sender_task:
            sender_task.cancel()

    try:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                break

            # Binary message = a pushed camera frame.
            data = message.get("bytes")
            if data is not None:
                if isinstance(session, PushAnalysisSession) and not stop_event.is_set():
                    _push_inbound(data)
                continue

            raw = message.get("text")
            if raw is None:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "message": "invalid json"}))
                continue

            action = msg.get("action")

            if action == "start":
                await _teardown_run()
                # Drain any stale inbound frames from a previous run.
                while not inbound.empty():
                    try:
                        inbound.get_nowait()
                    except Exception:  # noqa: BLE001
                        break
                stop_event.clear()
                pause_event.set()
                worker_thread = None
                camera_task = None
                try:
                    config = AnalysisConfig(**msg["config"])
                    if config.source == "camera":
                        session = PushAnalysisSession(config)
                    else:
                        session = await loop.run_in_executor(None, AnalysisSession, config)
                except Exception as exc:  # noqa: BLE001
                    await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
                    continue
                await ws.send_text(json.dumps({"type": "started", "usecase": config.usecase}))
                if monitor:
                    monitor.close()
                monitor = StreamMonitor(config.usecase, session.analyzer.title)
                if config.source == "camera":
                    camera_task = asyncio.create_task(camera_worker(session))
                else:
                    worker_thread = threading.Thread(target=worker, daemon=True)
                    worker_thread.start()
                sender_task = asyncio.create_task(sender())

            elif action == "pause":
                pause_event.clear()
                await ws.send_text(json.dumps({"type": "paused"}))

            elif action == "resume":
                pause_event.set()
                await ws.send_text(json.dumps({"type": "resumed"}))

            elif action == "config":
                with params_lock:
                    pending_params.update(msg.get("params", {}))
                await ws.send_text(json.dumps({"type": "config_ack"}))

            elif action == "stop":
                stop_event.set()
                await ws.send_text(json.dumps({"type": "stopped"}))

            else:
                await ws.send_text(json.dumps({"type": "error", "message": f"unknown action {action}"}))

    except WebSocketDisconnect:
        logger.info("client disconnected")
    finally:
        stop_event.set()
        if camera_task:
            try:
                inbound.put_nowait(None)
            except Exception:  # noqa: BLE001
                pass
            camera_task.cancel()
        if sender_task:
            sender_task.cancel()
        if worker_thread and worker_thread.is_alive():
            worker_thread.join(timeout=2)
        if session:
            session.close()
        if monitor:
            monitor.close()
