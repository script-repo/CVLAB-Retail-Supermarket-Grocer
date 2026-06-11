"""End-to-end agentic-ops test (also a demo-day pre-flight).

Synthesizes a shelf video (stocked -> emptied -> restocked), uploads it, runs
UC-2 over /ws/analyze, and listens on /ws/agent for the full chain:

    detected event -> agent run (NAI) -> work order -> notification
    -> cleared event -> clearance run -> work order resolved

Finally requests the NAI shift report. Exits non-zero if any link is missing.

Run with the backend venv while the server is up:
    cd cv-lab/backend && .venv/Scripts/python ../e2e_agent_test.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import cv2
import httpx
import numpy as np
import websockets

BASE = "http://localhost:8000"
WS = "ws://localhost:8000"
FPS = 12
W, H = 640, 360


def make_video(path: Path) -> None:
    """Stocked (6s) -> emptied (14s) -> restocked (14s)."""
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))

    def shelf_frame(stocked: bool) -> np.ndarray:
        f = np.full((H, W, 3), 205, np.uint8)
        cv2.rectangle(f, (20, 40), (620, 330), (150, 150, 150), -1)   # shelf unit
        for row_y in (60, 150, 240):                                   # three shelves
            cv2.rectangle(f, (30, row_y + 70), (610, row_y + 78), (90, 90, 90), -1)
            if stocked:
                for x in range(40, 600, 52):                           # product facings
                    color = ((x * 37) % 180 + 40, (x * 91) % 180 + 40, (x * 53) % 180 + 40)
                    cv2.rectangle(f, (x, row_y), (x + 42, row_y + 66), color, -1)
                    cv2.rectangle(f, (x, row_y), (x + 42, row_y + 66), (30, 30, 30), 2)
                    cv2.putText(f, "9.9", (x + 6, row_y + 40), cv2.FONT_HERSHEY_SIMPLEX,
                                0.45, (255, 255, 255), 1)
        # Mild noise so frames aren't identical.
        noise = np.random.default_rng(0).integers(-4, 4, f.shape, dtype=np.int16)
        return np.clip(f.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    for phase, secs in ((True, 6), (False, 14), (True, 14)):
        frame = shelf_frame(phase)
        for _ in range(secs * FPS):
            vw.write(frame)
    vw.release()


async def main() -> int:
    video = Path(tempfile.gettempdir()) / "uc02-e2e.mp4"
    make_video(video)
    print(f"synthetic video: {video} ({video.stat().st_size//1024} KiB)")

    async with httpx.AsyncClient(timeout=600) as http:
        r = await http.post(f"{BASE}/api/videos",
                            files={"file": ("uc02-e2e.mp4", video.read_bytes(), "video/mp4")})
        r.raise_for_status()
        vid = r.json()["id"]
        print(f"uploaded video id={vid}")

        seen: dict[str, list] = {"event": [], "agent_run": [], "agent_step": [],
                                 "workorder": [], "notification": []}

        async def watch_agent() -> None:
            async with websockets.connect(f"{WS}/ws/agent", max_size=None) as ws:
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type")
                    if t in seen:
                        seen[t].append(msg)
                        if t == "event":
                            e = msg["event"]
                            print(f"  EVENT {e['id']} {e['kind']}: {e['headline']}")
                        elif t == "agent_run":
                            print(f"  AGENT {msg['run_id']} start ({msg['mode']})")
                        elif t == "agent_step":
                            print(f"    step[{msg['kind']}] {msg['label']}: {str(msg['detail'])[:90]}")
                        elif t == "workorder":
                            w = msg["workorder"]
                            print(f"  WORKORDER {w['id']} {w['status']} prio={w['priority']} -> {w['assignee']}")
                        elif t == "notification":
                            print(f"  NOTIFY {msg['recipient']}: {str(msg['message'])[:80]}")

        async def drive_stream() -> None:
            cfg = {"video_id": vid, "usecase": "uc-02", "zones": [],
                   "params": {"threshold": 0.5}, "loop": False}
            async with websockets.connect(f"{WS}/ws/analyze", max_size=None) as ws:
                await ws.send(json.dumps({"action": "start", "config": cfg}))
                frames = 0
                try:
                    async with asyncio.timeout(180):
                        async for raw in ws:
                            if isinstance(raw, bytes):
                                frames += 1
                                continue
                            m = json.loads(raw)
                            if m.get("type") == "error":
                                print("STREAM ERROR:", m["message"])
                                return
                except (TimeoutError, websockets.ConnectionClosed):
                    pass
                print(f"stream ended after {frames} frames")

        watcher = asyncio.create_task(watch_agent())
        await drive_stream()
        # Allow trailing agent runs (clearance) to finish.
        for _ in range(60):
            resolved = [w for w in seen["workorder"] if w["workorder"]["status"] == "resolved"]
            if resolved:
                break
            await asyncio.sleep(2)
        watcher.cancel()

        print("\n--- shift report ---")
        r = await http.post(f"{BASE}/api/agent/report")
        if r.status_code == 200:
            print(r.json()["report"][:1200])
            report_ok = True
        else:
            print("REPORT FAILED:", r.status_code, r.text[:200])
            report_ok = False

    detected = [m for m in seen["event"] if m["event"]["kind"] == "detected"]
    cleared = [m for m in seen["event"] if m["event"]["kind"] == "cleared"]
    created = [m for m in seen["workorder"] if m["workorder"]["status"] == "open"]
    resolved = [m for m in seen["workorder"] if m["workorder"]["status"] == "resolved"]
    fallback = [m for m in seen["agent_step"] if m["kind"] == "error"]

    print("\n--- verdict ---")
    checks = {
        "detected event": bool(detected),
        "agent run started": bool(seen["agent_run"]),
        "work order created": bool(created),
        "notification sent": bool(seen["notification"]),
        "cleared event": bool(cleared),
        "work order resolved": bool(resolved),
        "no NAI fallback used": not fallback,
        "shift report generated": report_ok,
    }
    for k, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {k}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
