"""UC-4: Shrink / Loss Prevention and Theft Detection.

Privacy-respecting behaviour analytics (no identity/biometrics). Tracks people
(COCO person + ByteTrack) and bags (backpack/handbag/suitcase). A tracked person
who lingers (dwell) AND has a bag in close proximity raises a "review event" for
staff to assess — flagged as suspicious behaviour, never "confirmed theft".

With a pose model (``POSE_MODEL``), each person's wrists are tracked. A
shelf-to-bag gesture is a hand moving into a bag's box within
``gesture_window_s`` (default 3 s) of that person reaching (arm raised or
stretched out). Simply carrying a bag doesn't count. Gestures are shown on the
person and reported as evidence on the review. ``require_gesture``
(off by default) only flags people who made one, cutting false positives from
shoppers who merely linger with a bag.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model, get_pose_model
from app.core.tracking import Tracker
from app.schemas import AnalysisConfig

from .base import BRAND_GREEN, BRAND_RED, UseCaseAnalyzer, draw_banner, draw_chip, register
from .common import (BAG_CLASSES, detect, detect_groups, detect_people, draw_skeleton, is_reaching,
                     keypoints, PERSON, wrists)


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
        self.pose = get_pose_model()
        self.require_gesture = str(config.params.get("require_gesture", False)).lower() in ("1", "true", "yes")
        self.gestures: dict[int, int] = {}   # track id -> hand-to-bag gestures
        self._hand_in: dict[int, bool] = {}
        self._last_reach: dict[int, float] = {}
        self.gesture_window_s = float(config.params.get("gesture_window_s", 3.0))
        self.tracker = Tracker(frame_rate=self.fps)
        self.dwell_s = float(config.params.get("review_dwell_s", 4.0))
        self.proximity = float(config.params.get("bag_proximity_frac", 0.18)) * w
        self.box = None
        self.review_ids: set[int] = set()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        if self.pose is None:
            found = detect_groups(self.model, frame, {
                "people": ([PERSON], 0.35), "bags": (list(BAG_CLASSES.keys()), 0.3)})
            people, bags = found["people"], found["bags"]
        else:
            people = detect_people(self.pose, self.model, frame)
            bags = detect(self.model, frame, classes=list(BAG_CLASSES.keys()), conf=0.3)
        people = self.tracker.update(people, timestamp_s)
        bag_centers = [_center(b) for b in bags.xyxy]
        bag_boxes = []
        for x1, y1, x2, y2 in bags.xyxy:  # grown 15% so a hand at the opening counts
            gx, gy = 0.15 * (x2 - x1), 0.15 * (y2 - y1)
            bag_boxes.append((x1 - gx, y1 - gy, x2 + gx, y2 + gy))

        reviews_now = 0
        if people.tracker_id is not None:
            for i, (b, tid) in enumerate(zip(people.xyxy, people.tracker_id)):
                tid = int(tid)
                pc = _center(b)
                dwell = self.tracker.dwell_seconds(tid)
                near_bag = any(abs(pc[0]-bc[0]) < self.proximity and abs(pc[1]-bc[1]) < self.proximity
                               for bc in bag_centers)
                kp = keypoints(people, i)
                if kp is not None:
                    if is_reaching(kp):
                        self._last_reach[tid] = timestamp_s
                    hand_in = any(x1 <= wx <= x2 and y1 <= wy <= y2
                                  for wx, wy in wrists(kp) for x1, y1, x2, y2 in bag_boxes)
                    recent_reach = timestamp_s - self._last_reach.get(tid, -1e9) <= self.gesture_window_s
                    if hand_in and not self._hand_in.get(tid, False) and recent_reach:
                        self.gestures[tid] = self.gestures.get(tid, 0) + 1
                        self._last_reach.pop(tid, None)  # one gesture per reach
                    self._hand_in[tid] = hand_in
                gestures = self.gestures.get(tid, 0)
                suspicious = dwell >= self.dwell_s and near_bag
                if self.require_gesture and self.pose is not None:
                    suspicious = suspicious and gestures > 0
                color = BRAND_RED if suspicious else BRAND_GREEN
                if kp is not None:
                    draw_skeleton(frame, kp, color)
                cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), color, 2)
                if suspicious:
                    self.review_ids.add(tid)
                    reviews_now += 1
                    label = f"REVIEW #{tid}" + (f"  shelf>bag x{gestures}" if gestures else "")
                    draw_chip(frame, label, (int(b[0]), max(18, int(b[1]))), BRAND_RED)
                else:
                    label = f"#{tid} {dwell:0.0f}s" + (f"  shelf>bag x{gestures}" if gestures else "")
                    draw_chip(frame, label, (int(b[0]), max(18, int(b[1]))), BRAND_GREEN)
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
            "pose": self.pose is not None,
            "shelf_to_bag_gestures": int(sum(self.gestures.values())),
            "review_gestures": {str(t): self.gestures.get(t, 0) for t in sorted(self.review_ids)},
            "note": "behaviour flag only — not identity tracking",
        }
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
