"""UC-17: Visual Product Search ("find it on the shelf").

Identifies the most prominent product held up to the camera (largest COCO
detection) and maps it to a catalog location (aisle/bay). In production an
open-vocabulary model (Grounding DINO) or an embedding index backs arbitrary SKUs;
the COCO detector demonstrates the recognize -> locate flow.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, UseCaseAnalyzer, draw_banner, register
from .common import GROCERY_CLASSES, class_label, detect

AISLE_MAP = {
    "bottle": "Aisle 7 - Beverages", "wine glass": "Aisle 9 - Housewares",
    "cup": "Aisle 9 - Housewares", "bowl": "Aisle 9 - Housewares",
    "banana": "Produce - Bay 1", "apple": "Produce - Bay 2",
    "orange": "Produce - Bay 2", "broccoli": "Produce - Bay 4",
    "carrot": "Produce - Bay 4", "sandwich": "Aisle 1 - Deli",
    "pizza": "Aisle 12 - Frozen", "donut": "Aisle 3 - Bakery",
    "cake": "Aisle 3 - Bakery", "hot dog": "Aisle 5 - Meat",
    "backpack": "Aisle 14 - Seasonal", "handbag": "Aisle 14 - Seasonal",
}


@register
class VisualSearchAnalyzer(UseCaseAnalyzer):
    id = "uc-17"
    title = "Visual Product Search"
    pattern = "product-recognition"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        items = detect(self.model, frame, classes=list(GROCERY_CLASSES.keys()), conf=0.4)
        match_name = None
        aisle = None
        if len(items):
            areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in items.xyxy]
            idx = int(np.argmax(areas))
            b = items.xyxy[idx]
            match_name = class_label(items, idx)
            aisle = AISLE_MAP.get(match_name, "See store directory")
            x0, y0, x1, y1 = [int(v) for v in b]
            cv2.rectangle(frame, (x0, y0), (x1, y1), BRAND_CYAN, 3)
            cv2.putText(frame, f"MATCH: {match_name}", (x0, max(16, y0 - 28)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, BRAND_CYAN, 2, cv2.LINE_AA)
            cv2.putText(frame, aisle, (x0, max(14, y0 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, BRAND_GREEN, 2, cv2.LINE_AA)

        headline = (f"Match: {match_name} → {aisle}" if match_name
                    else "Hold a product up to the camera")
        draw_banner(frame, headline, alert=False)
        metrics = {"match": match_name, "location": aisle, "candidates": len(items)}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
