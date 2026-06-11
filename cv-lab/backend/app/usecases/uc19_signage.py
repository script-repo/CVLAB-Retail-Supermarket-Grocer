"""UC-19: Personalized Digital Signage Trigger (anonymous).

Anonymous audience analytics only — no identity, no demographics inference.
Tracks anonymous shopper tracks dwelling in front of a display zone; once dwell
passes the threshold, a contextual promotion is "triggered" for that anonymous
audience slot. Reports current audience and total impressions served.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_person_model
from app.core.tracking import Tracker
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, BRAND_ORANGE, UseCaseAnalyzer, draw_banner, draw_chip, register
from .common import PERSON, detect, rect_pts, zone_from_config


@register
class SignageAnalyzer(UseCaseAnalyzer):
    id = "uc-19"
    title = "Personalized Digital Signage Trigger (anonymous)"
    pattern = "privacy"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_person_model()
        self.tracker = Tracker(frame_rate=self.fps)
        self.trigger_s = float(config.params.get("trigger_seconds", 2.0))
        name, pts = zone_from_config(config, w, h, rect_pts(0.25, 0.25, 0.75, 0.95, w, h))
        self.polygon = pts
        self.zone = sv.PolygonZone(polygon=pts, triggering_anchors=(sv.Position.BOTTOM_CENTER,))
        self.impressions: set[int] = set()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        people = detect(self.model, frame, classes=[PERSON])
        people = self.tracker.update(people, timestamp_s)
        in_mask = self.zone.trigger(people)
        in_zone = people[in_mask] if len(people) else people

        triggered_now = 0
        if in_zone.tracker_id is not None:
            for b, tid in zip(in_zone.xyxy, in_zone.tracker_id):
                d = self.tracker.dwell_seconds(int(tid))
                if d >= self.trigger_s:
                    self.impressions.add(int(tid))
                    triggered_now += 1
                    draw_chip(frame, "PROMO SERVED", (int(b[0]), max(18, int(b[1]))), BRAND_ORANGE)
                else:
                    draw_chip(frame, f"{d:0.1f}s", (int(b[0]), max(18, int(b[1]))), BRAND_CYAN)

        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], BRAND_GREEN)
        cv2.addWeighted(overlay, 0.1, frame, 0.9, 0, frame)
        cv2.polylines(frame, [self.polygon], True, BRAND_GREEN, 2)

        headline = f"Audience: {len(in_zone)}  ·  promo active: {triggered_now}  ·  impressions: {len(self.impressions)}"
        draw_banner(frame, headline, alert=False)
        metrics = {"audience": len(in_zone), "active_promotions": triggered_now,
                   "impressions": len(self.impressions), "identity": "anonymous"}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
