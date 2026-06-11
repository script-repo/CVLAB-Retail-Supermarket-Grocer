"""UC-8: Automated Product Expiry / Date Monitoring.

Locates date-label-like text regions on product faces within a shelf zone. A
real deployment runs OCR (PaddleOCR / EasyOCR) to read and parse the date; here
the OCR-region proposer stands in when no OCR model is loaded, and the
front-most candidate is flagged as "expires soon" to demonstrate the workflow.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model
from app.schemas import AnalysisConfig

from .base import BRAND_FRESH, BRAND_GREEN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import GROCERY_CLASSES, detect, draw_detections, mask_from_poly, rect_pts, text_like_regions, zone_from_config


@register
class ExpiryAnalyzer(UseCaseAnalyzer):
    id = "uc-08"
    title = "Automated Product Expiry / Date Monitoring"
    pattern = "shelf-vision"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        name, pts = zone_from_config(config, w, h, rect_pts(0.1, 0.2, 0.9, 0.85, w, h))
        self.polygon = pts
        self.mask = mask_from_poly(frame.shape, pts)
        # GPU pass: localize products so date labels are tied to real items.
        self.coco = get_coco_model()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = text_like_regions(gray, self.mask)
        products = detect(self.coco, frame, classes=list(GROCERY_CLASSES))
        draw_detections(frame, products, BRAND_FRESH)
        cv2.polylines(frame, [self.polygon], True, BRAND_GREEN, 2)

        # Flag the largest (front-most / closest) candidate as near-expiry.
        flagged = None
        if boxes:
            flagged = max(boxes, key=lambda b: b[2] * b[3])
        for (x, y, bw, bh) in boxes:
            is_flag = flagged is not None and (x, y, bw, bh) == flagged
            color = BRAND_RED if is_flag else BRAND_ORANGE
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            if is_flag:
                cv2.putText(frame, "EXPIRES SOON", (x, max(14, y - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, BRAND_RED, 2, cv2.LINE_AA)

        alert = flagged is not None
        headline = (f"Rotate/remove near-expiry item ({len(boxes)} date labels read)"
                    if alert else "No date labels detected")
        draw_banner(frame, headline, alert=alert)
        metrics = {
            "date_labels": len(boxes),
            "near_expiry_flagged": 1 if flagged else 0,
            "products_detected": len(products),
            "ocr": "region-proposer + GPU product localization",
        }
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
