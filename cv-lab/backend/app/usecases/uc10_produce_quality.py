"""UC-10: Produce Freshness / Quality Inspection.

Detects produce items (COCO: banana/apple/orange/broccoli/carrot) and scores each
for spoilage using a brown/dark-spot colour heuristic (bruising proxy). Items
above the spoilage threshold are flagged for removal. A specialized produce-defect
model can be dropped in via the model registry for production accuracy.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model
from app.schemas import AnalysisConfig

from .base import BRAND_GREEN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import PRODUCE_CLASSES, brown_fraction, class_label, detect


@register
class ProduceQualityAnalyzer(UseCaseAnalyzer):
    id = "uc-10"
    title = "Produce Freshness / Quality Inspection"
    pattern = "product-recognition"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()
        self.spoil_threshold = float(config.params.get("spoilage_threshold", 0.18))

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        produce = detect(self.model, frame, classes=list(PRODUCE_CLASSES.keys()), conf=0.35)
        good = poor = 0
        for i, b in enumerate(produce.xyxy):
            x0, y0, x1, y1 = [int(v) for v in b]
            roi = frame[max(0, y0):y1, max(0, x0):x1]
            spoil = brown_fraction(roi)
            is_poor = spoil >= self.spoil_threshold
            color = BRAND_RED if is_poor else BRAND_GREEN
            if is_poor:
                poor += 1
            else:
                good += 1
            cv2.rectangle(frame, (x0, y0), (x1, y1), color, 2)
            label = f"{class_label(produce, i)} {'POOR' if is_poor else 'OK'} {int(spoil*100)}%"
            cv2.putText(frame, label, (x0, max(14, y0 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

        alert = poor > 0
        headline = (f"Remove {poor} poor-quality item(s) · {good} fresh" if alert
                    else f"All {good} produce items fresh")
        draw_banner(frame, headline, alert=alert)
        metrics = {"produce_detected": len(produce), "fresh": good, "poor": poor,
                   "spoilage_threshold": self.spoil_threshold}
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
