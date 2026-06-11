"""UC-1: Autonomous / Cashierless Checkout.

Tracks shoppers (COCO person + ByteTrack), associates nearby grocery-item
detections as a virtual basket, and fires an exit event when a tracked shopper
crosses a configurable exit line. Demonstrates "journey tracked without a lane".
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_coco_model
from app.core.tracking import Tracker
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_FRESH, BRAND_GREEN, UseCaseAnalyzer, draw_banner, draw_chip, register
from .common import GROCERY_CLASSES, PERSON, detect


@register
class CashierlessAnalyzer(UseCaseAnalyzer):
    id = "uc-01"
    title = "Autonomous / Cashierless Checkout"
    pattern = "people-tracking"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()
        self.tracker = Tracker(frame_rate=self.fps)
        self.item_classes = list(GROCERY_CLASSES.keys())
        # Exit line: vertical line near the right edge (or from a drawn 2-point zone).
        if config.zones and len(config.zones[0].points) >= 2:
            p = config.zones[0].points
            start = sv.Point(int(p[0][0] * w), int(p[0][1] * h))
            end = sv.Point(int(p[1][0] * w), int(p[1][1] * h))
        else:
            start = sv.Point(int(0.82 * w), int(0.05 * h))
            end = sv.Point(int(0.82 * w), int(0.95 * h))
        self.line = sv.LineZone(start=start, end=end)
        self.box = sv.BoxAnnotator(thickness=2)
        self.basket = 0

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        people = detect(self.model, frame, classes=[PERSON])
        people = self.tracker.update(people, timestamp_s)
        items = detect(self.model, frame, classes=self.item_classes, conf=0.4)
        self.basket = len(items)

        self.line.trigger(people)
        exits = int(self.line.out_count + self.line.in_count)

        # Draw exit line
        cv2.line(frame, (self.line.vector.start.x, self.line.vector.start.y),
                 (self.line.vector.end.x, self.line.vector.end.y), BRAND_GREEN, 2)
        cv2.putText(frame, "EXIT", (self.line.vector.start.x - 50, self.line.vector.start.y + 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, BRAND_GREEN, 2, cv2.LINE_AA)

        frame = self.box.annotate(frame, people)
        if people.tracker_id is not None:
            for b, tid in zip(people.xyxy, people.tracker_id):
                draw_chip(frame, f"shopper #{int(tid)}", (int(b[0]), max(18, int(b[1]))), BRAND_CYAN)
        for b in items.xyxy:
            cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), BRAND_FRESH, 2)

        headline = f"Shoppers: {len(people)}  ·  basket items: {self.basket}  ·  exits: {exits}"
        draw_banner(frame, headline, alert=False)
        metrics = {"shoppers": len(people), "basket_items": self.basket, "exit_events": exits}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
