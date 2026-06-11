"""Event bus bridging CV analyzers and the agentic layer.

Every analyzer already reports ``status: ok|alert`` plus a ``headline`` and
``values`` per frame. A :class:`StreamMonitor` watches those per-frame metrics
on the WebSocket sender path and turns *sustained* status transitions into
discrete events:

* ok -> alert held for N frames  => ``detected`` event (with a JPEG snapshot)
* alert -> ok held for M frames  => ``cleared`` event

The :class:`EventBus` fans those events (and any other typed message: agent
steps, work orders, notifications) out to WebSocket subscribers and to async
listeners such as the agent runtime. Because the contract is generic, this
works for all 20 use cases with zero analyzer changes.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.config import get_settings
from app.core import persist

logger = logging.getLogger(__name__)

_event_ids = itertools.count(1)


def _resume_event_ids() -> None:
    """Continue event numbering after a restart (avoids id collisions)."""
    global _event_ids
    try:
        _event_ids = itertools.count(persist.max_numeric_id("events") + 1)
    except Exception:  # noqa: BLE001
        logger.exception("could not resume event ids; starting at 1")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Event:
    id: str
    kind: str                      # "detected" | "cleared"
    usecase: str
    usecase_title: str
    headline: str
    values: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "usecase": self.usecase,
            "usecase_title": self.usecase_title, "headline": self.headline,
            "values": self.values, "timestamp": self.timestamp,
        }


class EventBus:
    """In-process pub/sub: event history + snapshots + WS fanout + listeners."""

    def __init__(self) -> None:
        self.events: deque[Event] = deque(maxlen=200)
        self.snapshots: dict[str, bytes] = {}
        self._queues: set[asyncio.Queue] = set()
        self._listeners: list[Callable[[Event], Awaitable[None]]] = []

    # --- subscriptions (WebSocket fanout) ---
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def broadcast(self, message: dict[str, Any]) -> None:
        """Send a typed JSON-able message to all WS subscribers (non-blocking)."""
        for q in list(self._queues):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass  # slow client: drop rather than stall the pipeline

    # --- listeners (the agent runtime) ---
    def add_listener(self, fn: Callable[[Event], Awaitable[None]]) -> None:
        self._listeners.append(fn)

    async def publish(self, event: Event, snapshot: bytes | None = None) -> None:
        self.events.append(event)
        if snapshot:
            self.snapshots[event.id] = snapshot
            # Keep memory bounded: only retain snapshots for stored events.
            live_ids = {e.id for e in self.events}
            for k in [k for k in self.snapshots if k not in live_ids]:
                del self.snapshots[k]
        logger.info("event %s: %s [%s] %s", event.id, event.kind, event.usecase, event.headline)
        try:
            persist.save_event(event.to_dict(), event.ts, snapshot)
        except Exception:  # noqa: BLE001
            logger.exception("event persistence failed (continuing in-memory)")
        self.broadcast({"type": "event", "event": event.to_dict(),
                        "has_snapshot": snapshot is not None})
        for fn in self._listeners:
            asyncio.get_running_loop().create_task(self._safe(fn, event))

    @staticmethod
    async def _safe(fn: Callable[[Event], Awaitable[None]], event: Event) -> None:
        try:
            await fn(event)
        except Exception:  # noqa: BLE001
            logger.exception("event listener failed for %s", event.id)

    def get_event(self, event_id: str) -> Event | None:
        return next((e for e in self.events if e.id == event_id), None)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
        _resume_event_ids()
        try:
            saved = persist.load_state()
            for e in saved["events"]:
                _bus.events.append(Event(**e))
            _bus.snapshots.update(saved["snapshots"])
            if saved["events"]:
                logger.info("rehydrated %d events from disk", len(saved["events"]))
        except Exception:  # noqa: BLE001
            logger.exception("could not rehydrate events; starting empty")
    return _bus


# --- Live metrics registry (for the agent's get_live_metrics tool) ----------

LIVE_METRICS: dict[str, dict[str, Any]] = {}


class StreamMonitor:
    """Per-analysis-stream transition detector. Fed from the WS sender path."""

    def __init__(self, usecase: str, usecase_title: str):
        s = get_settings()
        self.usecase = usecase
        self.usecase_title = usecase_title
        self.detect_frames = s.agent_detect_frames
        self.clear_frames = s.agent_clear_frames
        self.in_alert = False
        self._alert_run = 0
        self._ok_run = 0
        self._last_alert_metrics: dict[str, Any] = {}

    async def feed(self, metrics: dict[str, Any], jpeg: bytes) -> None:
        status = metrics.get("status", "ok")
        LIVE_METRICS[self.usecase] = {
            "usecase": self.usecase, "title": self.usecase_title,
            "status": status, "headline": metrics.get("headline", ""),
            "values": metrics.get("values", {}), "updated": _now_iso(),
        }
        bus = get_event_bus()
        if status == "alert":
            self._ok_run = 0
            self._alert_run += 1
            self._last_alert_metrics = metrics
            if not self.in_alert and self._alert_run >= self.detect_frames:
                self.in_alert = True
                ev = Event(
                    id=f"ev-{next(_event_ids):04d}", kind="detected",
                    usecase=self.usecase, usecase_title=self.usecase_title,
                    headline=metrics.get("headline", "Alert"),
                    values=dict(metrics.get("values", {})),
                )
                await bus.publish(ev, snapshot=jpeg)
        else:
            self._alert_run = 0
            self._ok_run += 1
            if self.in_alert and self._ok_run >= self.clear_frames:
                self.in_alert = False
                ev = Event(
                    id=f"ev-{next(_event_ids):04d}", kind="cleared",
                    usecase=self.usecase, usecase_title=self.usecase_title,
                    headline=f"Condition cleared — {metrics.get('headline', 'status OK')}",
                    values=dict(metrics.get("values", {})),
                )
                await bus.publish(ev, snapshot=jpeg)

    def close(self) -> None:
        LIVE_METRICS.pop(self.usecase, None)
