"""In-cluster smoke test: build every registered analyzer and run a few frames.

Run inside the pod:
    cd /app/backend && PYTHONPATH=/deps python /app/selftest.py
Exits non-zero if any analyzer raises.
"""
import sys
import traceback

import cv2
import numpy as np

import app.usecases as U
from app.schemas import AnalysisConfig

ids = [u["id"] for u in U.list_usecases()]
print(f"REGISTERED {len(ids)}: {ids}", flush=True)

# Synthetic frame with shelf-like structure so heuristics have texture to work on.
frame = np.full((360, 640, 3), 200, np.uint8)
cv2.rectangle(frame, (40, 70), (600, 310), (120, 120, 120), -1)
for x in range(60, 600, 80):
    cv2.rectangle(frame, (x, 90), (x + 55, 290), (70, 160, 90), -1)
cv2.putText(frame, "12/2026  $4.99", (70, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2)

fails = []
for uid in ids:
    try:
        cls = U.get_analyzer_cls(uid)
        analyzer = cls(fps=10)
        cfg = AnalysisConfig(video_id="t", usecase=uid)
        analyzer.setup(frame.copy(), cfg)
        last = {}
        for i in range(3):
            out, last = analyzer.process_frame(frame.copy(), i * 0.2)
            assert out is not None and out.shape == frame.shape, "bad frame"
            assert isinstance(last, dict) and "status" in last, "bad metrics"
        print(f"OK   {uid}  status={last.get('status')}  headline={str(last.get('headline'))[:60]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        fails.append(uid)
        print(f"FAIL {uid}: {exc!r}", flush=True)
        traceback.print_exc()

print(f"DONE  passed={len(ids)-len(fails)}/{len(ids)}  fails={fails}", flush=True)
sys.exit(1 if fails else 0)
