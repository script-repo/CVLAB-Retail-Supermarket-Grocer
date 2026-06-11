"""UC-15: Cold-Chain / Freezer-Door Open-Time Monitoring.

Watches a fridge/freezer door region and detects open vs closed from the change
against a rolling-baseline (open doors reveal lit interiors / motion). Times how
long the door stays open and raises an alert past the allowed threshold — a proxy
for energy waste and cold-chain risk.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_person_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import PERSON, detect, draw_detections, mask_from_poly, rect_pts, zone_from_config


@register
class ColdChainAnalyzer(UseCaseAnalyzer):
    id = "uc-15"
    title = "Cold-Chain / Freezer-Door Monitoring"
    pattern = "task-ops"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.max_open_s = float(config.params.get("max_open_seconds", 5.0))
        self.diff_threshold = float(config.params.get("door_diff_threshold", 18.0))
        name, pts = zone_from_config(config, w, h, rect_pts(0.3, 0.1, 0.7, 0.9, w, h))
        self.polygon = pts
        self.mask = mask_from_poly(frame.shape, pts)
        self.baseline_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.open_since = None
        self._last_ts = None
        # GPU pass: detect the shopper/associate at the door (context for the
        # open-door timer; an open door with nobody present is the worst case).
        self.person_model = get_person_model()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, self.baseline_gray)
        diff = cv2.bitwise_and(diff, diff, mask=self.mask)
        area = max(1, int(np.count_nonzero(self.mask)))
        mean_change = float(diff.sum()) / area
        is_open = mean_change > self.diff_threshold

        if is_open:
            if self.open_since is None:
                self.open_since = timestamp_s
            open_for = timestamp_s - self.open_since
        else:
            self.open_since = None
            open_for = 0.0
            # Slowly adapt baseline while closed to handle lighting drift.
            self.baseline_gray = cv2.addWeighted(self.baseline_gray, 0.9, gray, 0.1, 0)

        people = detect(self.person_model, frame, classes=[PERSON])
        draw_detections(frame, people, BRAND_CYAN, label="person")
        unattended = is_open and len(people) == 0

        alert = is_open and open_for > self.max_open_s
        color = BRAND_RED if (is_open) else BRAND_GREEN
        cv2.polylines(frame, [self.polygon], True, color, 3)
        state = "OPEN" if is_open else "CLOSED"
        if alert:
            headline = f"DOOR OPEN {open_for:0.1f}s — exceeds {self.max_open_s:0.0f}s!"
            if unattended:
                headline += " (unattended)"
        else:
            headline = f"Door {state}" + (f" {open_for:0.1f}s" if is_open else "")
        draw_banner(frame, headline, alert=alert)
        metrics = {"door_state": state, "open_seconds": round(open_for, 1),
                   "max_open_seconds": self.max_open_s, "alert": bool(alert),
                   "people_at_door": len(people), "unattended": bool(unattended)}
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
