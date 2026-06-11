"""UC-5: Self-Checkout Fraud / Scan-Avoidance Detection.

Watches the bagging zone of a self-checkout. Items detected entering the bagging
zone are counted; the POS scan stream (simulated here on a fixed cadence) is
reconciled against them. When bagged items exceed recorded scans, a
"skipped scan" mismatch is raised for attendant review.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_coco_model
from app.core.tracking import Tracker
from app.schemas import AnalysisConfig

from .base import BRAND_GREEN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import GROCERY_CLASSES, detect, rect_pts, zone_from_config


@register
class SelfCheckoutAnalyzer(UseCaseAnalyzer):
    id = "uc-05"
    title = "Self-Checkout Fraud / Scan-Avoidance Detection"
    pattern = "loss-prevention"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()
        self.tracker = Tracker(frame_rate=self.fps)
        self.item_classes = list(GROCERY_CLASSES.keys())
        self.scan_period_s = float(config.params.get("scan_period_s", 3.0))
        name, pts = zone_from_config(config, w, h, rect_pts(0.55, 0.45, 0.95, 0.95, w, h))
        self.polygon = pts
        self.zone = sv.PolygonZone(polygon=pts, triggering_anchors=(sv.Position.CENTER,))
        self.bagged_ids: set[int] = set()
        self.scans = 0

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        items = detect(self.model, frame, classes=self.item_classes, conf=0.4)
        items = self.tracker.update(items, timestamp_s)
        in_mask = self.zone.trigger(items)
        in_zone = items[in_mask] if len(items) else items
        if in_zone.tracker_id is not None:
            for tid in in_zone.tracker_id:
                self.bagged_ids.add(int(tid))

        # Simulated POS scan cadence.
        self.scans = int(timestamp_s // self.scan_period_s)
        bagged = len(self.bagged_ids)
        skipped = max(0, bagged - self.scans)

        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], BRAND_ORANGE)
        cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
        cv2.polylines(frame, [self.polygon], True, BRAND_ORANGE, 2)
        cv2.putText(frame, "BAGGING", (int(self.polygon[:, 0].min()) + 4, int(self.polygon[:, 1].min()) + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, BRAND_ORANGE, 2, cv2.LINE_AA)
        for b in in_zone.xyxy:
            cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), BRAND_GREEN, 2)

        alert = skipped > 0
        headline = (f"SCAN MISMATCH — {skipped} item(s) not scanned" if alert
                    else f"Bagged {bagged} · scanned {self.scans} · OK")
        draw_banner(frame, headline, alert=alert)
        metrics = {"bagged_items": bagged, "scans": self.scans, "skipped_scans": skipped}
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
