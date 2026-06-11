"""Thin wrapper around supervision's ByteTrack + detection helpers.

Centralizes the conversion from Ultralytics results to supervision Detections
and the multi-object tracker so each use-case stays small.
"""
from __future__ import annotations

import numpy as np
import supervision as sv


def detections_from_yolo(result, allowed_classes: set[int] | None = None) -> sv.Detections:
    """Convert a single Ultralytics result to supervision Detections."""
    det = sv.Detections.from_ultralytics(result)
    if allowed_classes is not None and det.class_id is not None and len(det) > 0:
        mask = np.isin(det.class_id, list(allowed_classes))
        det = det[mask]
    return det


class Tracker:
    """ByteTrack wrapper that also exposes per-track dwell timing."""

    def __init__(self, frame_rate: int = 12):
        self.bytetrack = sv.ByteTrack(frame_rate=frame_rate)
        self._first_seen: dict[int, float] = {}
        self._last_seen: dict[int, float] = {}

    def update(self, detections: sv.Detections, timestamp_s: float) -> sv.Detections:
        tracked = self.bytetrack.update_with_detections(detections)
        if tracked.tracker_id is not None:
            for tid in tracked.tracker_id:
                tid = int(tid)
                self._first_seen.setdefault(tid, timestamp_s)
                self._last_seen[tid] = timestamp_s
        return tracked

    def dwell_seconds(self, tracker_id: int) -> float:
        if tracker_id not in self._first_seen:
            return 0.0
        return self._last_seen.get(tracker_id, 0.0) - self._first_seen[tracker_id]

    def reset(self) -> None:
        self.bytetrack.reset()
        self._first_seen.clear()
        self._last_seen.clear()
