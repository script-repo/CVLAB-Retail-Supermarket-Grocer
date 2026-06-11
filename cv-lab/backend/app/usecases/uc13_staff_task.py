"""UC-13: Staff Task Completion / SOP Adherence.

Monitors a task area (zone) for staff presence and runs a simple state machine:
PENDING -> IN PROGRESS (staff present) -> COMPLETE (staff worked the area for the
required time, then left). Reports state and time-on-task — an objective SOP /
labour-compliance signal without identifying the worker.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_person_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, BRAND_ORANGE, UseCaseAnalyzer, draw_banner, register
from .common import PERSON, detect, rect_pts, zone_from_config


@register
class StaffTaskAnalyzer(UseCaseAnalyzer):
    id = "uc-13"
    title = "Staff Task Completion / SOP Adherence"
    pattern = "task-ops"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_person_model()
        self.required_s = float(config.params.get("required_seconds", 4.0))
        name, pts = zone_from_config(config, w, h, rect_pts(0.3, 0.3, 0.7, 0.95, w, h))
        self.zone_name, self.polygon = name, pts
        self.zone = sv.PolygonZone(polygon=pts, triggering_anchors=(sv.Position.BOTTOM_CENTER,))
        self.state = "PENDING"
        self.time_on_task = 0.0
        self._last_ts = None

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        dt = 0.0 if self._last_ts is None else max(0.0, timestamp_s - self._last_ts)
        self._last_ts = timestamp_s
        people = detect(self.model, frame, classes=[PERSON])
        in_mask = self.zone.trigger(people)
        present = int(np.count_nonzero(in_mask)) if len(people) else 0

        if self.state != "COMPLETE":
            if present > 0:
                self.state = "IN PROGRESS"
                self.time_on_task += dt
            elif self.state == "IN PROGRESS" and self.time_on_task >= self.required_s:
                self.state = "COMPLETE"

        color = {"PENDING": BRAND_ORANGE, "IN PROGRESS": BRAND_CYAN, "COMPLETE": BRAND_GREEN}[self.state]
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], color)
        cv2.addWeighted(overlay, 0.14, frame, 0.86, 0, frame)
        cv2.polylines(frame, [self.polygon], True, color, 2)
        for b in (people[in_mask].xyxy if present else []):
            cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), color, 2)

        headline = f"Task: {self.state}  ·  time-on-task {self.time_on_task:0.1f}s / {self.required_s:0.0f}s"
        draw_banner(frame, headline, alert=False)
        metrics = {"state": self.state, "time_on_task_s": round(self.time_on_task, 1),
                   "required_s": self.required_s, "staff_present": present}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
