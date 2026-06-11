"""UC-9: Smart-Cart / In-Cart Product Recognition.

Recognizes grocery items inside the cart/basket zone (COCO object detector) and
maintains a running cart with mock unit prices and a live subtotal — the
detection backbone behind a smart-cart or smart-basket experience.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_coco_model
from app.schemas import AnalysisConfig

from .base import BRAND_FRESH, BRAND_GREEN, UseCaseAnalyzer, draw_banner, register
from .common import GROCERY_CLASSES, MOCK_PRICES, class_label, detect, rect_pts, zone_from_config


@register
class SmartCartAnalyzer(UseCaseAnalyzer):
    id = "uc-09"
    title = "Smart-Cart / In-Cart Product Recognition"
    pattern = "product-recognition"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()
        self.item_classes = list(GROCERY_CLASSES.keys())
        name, pts = zone_from_config(config, w, h, rect_pts(0.25, 0.25, 0.75, 0.95, w, h))
        self.polygon = pts
        self.zone = sv.PolygonZone(polygon=pts, triggering_anchors=(sv.Position.CENTER,))

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        items = detect(self.model, frame, classes=self.item_classes, conf=0.4)
        in_mask = self.zone.trigger(items)
        in_zone = items[in_mask] if len(items) else items

        counts: Counter = Counter()
        for i in range(len(in_zone)):
            counts[class_label(in_zone, i)] += 1
        subtotal = sum(MOCK_PRICES.get(name, 0.0) * n for name, n in counts.items())

        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], BRAND_GREEN)
        cv2.addWeighted(overlay, 0.1, frame, 0.9, 0, frame)
        cv2.polylines(frame, [self.polygon], True, BRAND_GREEN, 2)
        for b in in_zone.xyxy:
            cv2.rectangle(frame, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), BRAND_FRESH, 2)
        # Cart list panel
        y = 70
        for name, n in counts.most_common():
            cv2.putText(frame, f"{n}x {name}  ${MOCK_PRICES.get(name,0)*n:0.2f}", (12, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, BRAND_GREEN, 2, cv2.LINE_AA)
            y += 24

        headline = f"Cart: {sum(counts.values())} items  ·  subtotal ${subtotal:0.2f}"
        draw_banner(frame, headline, alert=False)
        metrics = {"items_in_cart": int(sum(counts.values())),
                   "subtotal": round(subtotal, 2),
                   "breakdown": dict(counts)}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
