"""UC-18: Receiving-Dock Verification / Carton Counting.

Counts cartons/cases in the receiving zone using rectangular-contour detection
and reconciles the count against the expected PO quantity; a shortfall or excess
raises a discrepancy alert. Production deployments add OCR/barcode reading on each
carton; this build demonstrates the count-and-reconcile loop.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_person_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, BRAND_ORANGE, UseCaseAnalyzer, draw_banner, register
from .common import PERSON, detect, draw_detections, mask_from_poly, rect_pts, zone_from_config


@register
class ReceivingDockAnalyzer(UseCaseAnalyzer):
    id = "uc-18"
    title = "Receiving-Dock Verification / Carton Counting"
    pattern = "product-recognition"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.expected = int(config.params.get("expected_count", 0))  # 0 = no PO check
        name, pts = zone_from_config(config, w, h, rect_pts(0.08, 0.25, 0.92, 0.95, w, h))
        self.polygon = pts
        self.mask = mask_from_poly(frame.shape, pts)
        self.min_area = 0.004 * w * h
        # GPU pass: receiving staff on the dock (context for the carton count).
        self.person_model = get_person_model()

    def _count_cartons(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.bitwise_and(gray, gray, mask=self.mask)
        edges = cv2.Canny(gray, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in cnts:
            area = cv2.contourArea(c)
            if area < self.min_area:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.04 * peri, True)
            if 4 <= len(approx) <= 6:
                boxes.append(cv2.boundingRect(c))
        return boxes

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        boxes = self._count_cartons(frame)
        cv2.polylines(frame, [self.polygon], True, BRAND_GREEN, 2)
        for (x, y, bw, bh) in boxes:
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), BRAND_ORANGE, 2)
        staff = detect(self.person_model, frame, classes=[PERSON])
        draw_detections(frame, staff, BRAND_CYAN, label="staff")

        count = len(boxes)
        discrepancy = (self.expected > 0) and (count != self.expected)
        if self.expected > 0:
            headline = (f"DISCREPANCY: counted {count} / expected {self.expected}"
                        if discrepancy else f"Verified {count} / {self.expected} cartons")
        else:
            headline = f"Counted {count} cartons in receiving zone"
        draw_banner(frame, headline, alert=discrepancy)
        metrics = {"counted": count, "expected": self.expected,
                   "discrepancy": bool(discrepancy), "staff_on_dock": len(staff)}
        return frame, {"status": "alert" if discrepancy else "ok", "headline": headline, "values": metrics}
