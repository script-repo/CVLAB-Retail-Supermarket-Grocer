"""UC-14: Assisted Age Verification (privacy-preserving).

NO facial recognition or age estimation from biometrics. Detects only that a
shopper is present at the checkout zone and drives the attendant workflow for an
age-restricted purchase: AGE CHECK REQUIRED -> STAFF ASSIST -> APPROVED. The
camera confirms presence and hand-off only; the human makes the age decision.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_person_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import PERSON, detect, rect_pts, zone_from_config


@register
class AgeVerificationAnalyzer(UseCaseAnalyzer):
    id = "uc-14"
    title = "Assisted Age Verification (privacy-preserving)"
    pattern = "privacy"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_person_model()
        self.check_s = float(config.params.get("check_seconds", 3.0))
        self.assist_s = float(config.params.get("assist_seconds", 3.0))
        name, pts = zone_from_config(config, w, h, rect_pts(0.3, 0.3, 0.7, 0.95, w, h))
        self.polygon = pts
        self.zone = sv.PolygonZone(polygon=pts, triggering_anchors=(sv.Position.BOTTOM_CENTER,))
        self.state = "IDLE"
        self.t_in_state = 0.0
        self._last_ts = None

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        dt = 0.0 if self._last_ts is None else max(0.0, timestamp_s - self._last_ts)
        self._last_ts = timestamp_s
        people = detect(self.model, frame, classes=[PERSON])
        in_mask = self.zone.trigger(people)
        present = int(np.count_nonzero(in_mask)) if len(people) else 0

        self.t_in_state += dt
        if self.state == "IDLE":
            if present > 0:
                self.state, self.t_in_state = "AGE CHECK REQUIRED", 0.0
        elif self.state == "AGE CHECK REQUIRED":
            if present == 0:
                self.state, self.t_in_state = "IDLE", 0.0
            elif self.t_in_state >= self.check_s:
                self.state, self.t_in_state = "STAFF ASSIST", 0.0
        elif self.state == "STAFF ASSIST":
            if self.t_in_state >= self.assist_s:
                self.state, self.t_in_state = "APPROVED", 0.0
        elif self.state == "APPROVED":
            if present == 0:
                self.state, self.t_in_state = "IDLE", 0.0

        colors = {"IDLE": BRAND_GREEN, "AGE CHECK REQUIRED": BRAND_ORANGE,
                  "STAFF ASSIST": BRAND_CYAN, "APPROVED": BRAND_GREEN}
        color = colors[self.state]
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], color)
        cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
        cv2.polylines(frame, [self.polygon], True, color, 2)

        headline = f"{self.state}  ·  shopper present: {'yes' if present else 'no'}"
        draw_banner(frame, headline, alert=self.state == "AGE CHECK REQUIRED")
        metrics = {"state": self.state, "present": present,
                   "biometrics": "none — presence only"}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
