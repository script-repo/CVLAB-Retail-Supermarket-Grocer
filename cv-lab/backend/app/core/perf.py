"""Per-use-case processing-time attribution.

The GPU reports utilization per *process*, not per use case, so true
per-use-case GPU numbers don't exist at the driver level. Instead each
analysis stream records its frame processing time here; the UI apportions
the measured GPU utilization across active use cases by their share of
processing time over a rolling window. Honest, and accurate enough for a
stacked utilization bar.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=900))  # (ts, seconds)
_titles: dict[str, str] = {}


def record(usecase: str, title: str, seconds: float) -> None:
    """Record one frame's processing time for a use case."""
    with _lock:
        _titles[usecase] = title
        _samples[usecase].append((time.time(), seconds))


def snapshot(window_s: float = 5.0) -> list[dict]:
    """Active use cases over the window, with share of total processing time."""
    now = time.time()
    out: list[dict] = []
    with _lock:
        for uc, dq in _samples.items():
            recent = [s for t, s in dq if now - t <= window_s]
            if not recent:
                continue
            busy = sum(recent)
            out.append({
                "usecase": uc,
                "title": _titles.get(uc, uc),
                "fps": round(len(recent) / window_s, 1),
                "ms_per_frame": round(1000.0 * busy / len(recent), 1),
                "_busy": busy,
            })
    total = sum(o["_busy"] for o in out) or 1.0
    for o in out:
        o["share_pct"] = round(100.0 * o.pop("_busy") / total, 1)
    return sorted(out, key=lambda o: -o["share_pct"])
