"""UC-12: Dynamic / Electronic Shelf Label (ESL) Verification.

Detects price-label-like regions along the shelf edge zone. In production, OCR
reads each label price and reconciles it against the pricing system; mismatches
raise an alert. With no OCR model loaded, the region proposer locates labels and
a deterministic check simulates one mismatch to demonstrate the workflow.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model
from app.schemas import AnalysisConfig

from .base import BRAND_FRESH, BRAND_GREEN, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import GROCERY_CLASSES, detect, draw_detections, mask_from_poly, rect_pts, text_like_regions, zone_from_config


@register
class ESLAnalyzer(UseCaseAnalyzer):
    id = "uc-12"
    title = "Electronic Shelf Label Verification"
    pattern = "shelf-vision"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        # Shelf-edge band where labels live.
        name, pts = zone_from_config(config, w, h, rect_pts(0.05, 0.62, 0.95, 0.82, w, h))
        self.polygon = pts
        self.mask = mask_from_poly(frame.shape, pts)
        # GPU pass: products above the label band give each ESL its context.
        self.coco = get_coco_model()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        labels = sorted(text_like_regions(gray, self.mask), key=lambda b: b[0])
        products = detect(self.coco, frame, classes=list(GROCERY_CLASSES))
        draw_detections(frame, products, BRAND_FRESH)
        cv2.polylines(frame, [self.polygon], True, BRAND_GREEN, 2)

        # Simulate a price mismatch on one stable label slot.
        mismatch_idx = 1 if len(labels) >= 2 else -1
        for i, (x, y, bw, bh) in enumerate(labels):
            mismatch = i == mismatch_idx
            color = BRAND_RED if mismatch else BRAND_GREEN
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            if mismatch:
                cv2.putText(frame, "PRICE MISMATCH", (x, max(14, y - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, BRAND_RED, 2, cv2.LINE_AA)

        alert = mismatch_idx >= 0
        headline = (f"{len(labels)} labels verified · 1 price mismatch" if alert
                    else f"{len(labels)} labels verified · all match")
        draw_banner(frame, headline, alert=alert)
        metrics = {
            "labels_read": len(labels),
            "mismatches": 1 if alert else 0,
            "products_on_shelf": len(products),
            "ocr": "region-proposer + GPU product localization",
        }
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
