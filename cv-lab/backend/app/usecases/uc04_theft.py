"""UC-4: Shrink / Loss Prevention and Theft Detection.

Privacy-respecting behaviour analytics (no identity/biometrics). Tracks people
(COCO person + ByteTrack) and bags (backpack/handbag/suitcase). A tracked person
who lingers (dwell) AND has a bag in close proximity raises a "review event" for
staff to assess — flagged as suspicious behaviour, never "confirmed theft".
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model
from app.core.tracking import Tracker
from app.schemas import AnalysisConfig

from .base import BRAND_GREEN, BRAND_RED, UseCaseAnalyzer, draw_banner, draw_chip, register
from .common import BAG_CLASSES, PERSON, detect


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


@register
class TheftAnalyzer(UseCaseAnalyzer):
    id = "uc-04"
    title = "Shrink / Loss Prevention & Theft Detection"
    pattern = "loss-prevention"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()
        self.tracker = Tracker(frame_rate=self.fps)
        self.dwell_s = float(config.params.get("review_dwell_s", 4.0))
        self.proximity = float(config.params.get("bag_proximity_frac", 0.18)) * w
        self.box = None
        self.review_ids: set[int] = set()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        people = detect(self.model, frame, classes=[PERSON])
        people = self.tracker.update(people, timestamp_s)
        bags = detect(self.model, frame, classes=list(BAG_CLASSES.keys()), conf=0.3)
        bag_centers = [_center(b) for b in bags.xyxy]

        reviews_now = 0
        if people.tracker_id is not None:
            for b, tid in zip(people.xyxy, people.tracker_id):
                tid = int(tid)
                pc = _center(b)
                dwell = self.tracker.dwell_seconds(tid)
                near_bag = any(abs(pc[0]-bc[0]) < self.proximity and abs(pc[1]-bc[1]) < self.proximity
                               for bc in bag_centers)
                suspicious = dwell >= self.dwell_s and near_bag
                color = BRAND_RED if suspicious else BRAND_GREEN
                cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), color, 2)
                if suspicious:
                    self.review_ids.add(tid)
                    reviews_now += 1
                    draw_chip(frame, f"REVIEW #{tid}", (int(b[0]), max(18, int(b[1]))), BRAND_RED)
                else:
                    draw_chip(frame, f"#{tid} {dwell:0.0f}s", (int(b[0]), max(18, int(b[1]))), BRAND_GREEN)
        for b in bags.xyxy:
            cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 147, 239), 1)

        alert = reviews_now > 0
        headline = (f"REVIEW EVENT — suspicious behaviour ({reviews_now})" if alert
                    else "No anomalies — monitoring")
        draw_banner(frame, headline, alert=alert)
        metrics = {
            "people": len(people),
            "bags": len(bags),
            "active_reviews": reviews_now,
            "total_review_events": len(self.review_ids),
            "note": "behaviour flag only — not identity tracking",
        }
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
