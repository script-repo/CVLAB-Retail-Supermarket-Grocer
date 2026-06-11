"""SQLite persistence for agentic-ops state.

Events, snapshots, work orders, and notifications survive a process/pod
restart — important for the demo, where the shift report draws on the whole
morning. The DB lives under the local storage dir (a PVC in-cluster).

Writes are tiny and happen on the event loop; a module lock plus
check_same_thread=False keeps sqlite happy without an executor.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, kind TEXT, usecase TEXT, usecase_title TEXT,
    headline TEXT, values_json TEXT, timestamp TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS snapshots (event_id TEXT PRIMARY KEY, jpeg BLOB);
CREATE TABLE IF NOT EXISTS work_orders (id TEXT PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS notifications (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, json TEXT
);
"""


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        settings = get_settings()
        settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
        path = settings.local_storage_dir / "agentic.db"
        _conn = sqlite3.connect(str(path), check_same_thread=False)
        _conn.executescript(_SCHEMA)
        _conn.commit()
        logger.info("agentic state DB at %s", path)
    return _conn


def save_event(ev: dict[str, Any], ts: float, snapshot: bytes | None) -> None:
    with _lock:
        db = _db()
        db.execute(
            "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)",
            (ev["id"], ev["kind"], ev["usecase"], ev["usecase_title"],
             ev["headline"], json.dumps(ev["values"]), ev["timestamp"], ts))
        if snapshot:
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?)", (ev["id"], snapshot))
        db.commit()


def save_work_order(wo: dict[str, Any]) -> None:
    with _lock:
        db = _db()
        db.execute("INSERT OR REPLACE INTO work_orders VALUES (?,?)", (wo["id"], json.dumps(wo)))
        db.commit()


def save_notification(note: dict[str, Any]) -> None:
    with _lock:
        db = _db()
        db.execute("INSERT INTO notifications (json) VALUES (?)", (json.dumps(note),))
        db.commit()


def load_state(max_events: int = 200) -> dict[str, Any]:
    """Everything needed to rehydrate the bus and the agent runtime."""
    with _lock:
        db = _db()
        events = [
            {"id": r[0], "kind": r[1], "usecase": r[2], "usecase_title": r[3],
             "headline": r[4], "values": json.loads(r[5]), "timestamp": r[6], "ts": r[7]}
            for r in db.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (max_events,)).fetchall()
        ][::-1]
        snapshots = {r[0]: r[1] for r in db.execute(
            "SELECT event_id, jpeg FROM snapshots").fetchall()}
        work_orders = {r[0]: json.loads(r[1]) for r in db.execute(
            "SELECT id, json FROM work_orders").fetchall()}
        notifications = [json.loads(r[0]) for r in db.execute(
            "SELECT json FROM notifications ORDER BY seq DESC LIMIT 100").fetchall()][::-1]
    return {"events": events, "snapshots": snapshots,
            "work_orders": work_orders, "notifications": notifications}


def max_numeric_id(prefix_table: str) -> int:
    """Highest numeric suffix in stored ids (resume counters after restart)."""
    col = {"events": "id", "work_orders": "id"}[prefix_table]
    with _lock:
        rows = _db().execute(f"SELECT {col} FROM {prefix_table}").fetchall()  # noqa: S608
    best = 0
    for (rid,) in rows:
        digits = "".join(ch for ch in str(rid) if ch.isdigit())
        if digits:
            best = max(best, int(digits))
    return best
