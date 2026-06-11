"""UC-11: Autonomous Aisle-Scanning Robot (shelf audit).

Emulates a robot's scanning pass: a sweep line travels across the aisle on a
fixed cadence and, as it passes each shelf section, the section's edge-density is
audited for stock gaps (low texture = empty facing). Reports scan progress and
the gaps found on the current pass.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_FRESH, BRAND_GREEN, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import GROCERY_CLASSES, detect, draw_detections, edge_density


@register
class AisleRobotAnalyzer(UseCaseAnalyzer):
    id = "uc-11"
    title = "Autonomous Aisle-Scanning Robot"
    pattern = "task-ops"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.cols = int(config.params.get("sections", 8))
        self.period_s = float(config.params.get("scan_period_s", 8.0))
        self.gap_threshold = float(config.params.get("gap_edge_density", 0.02))
        self.y0, self.y1 = int(0.2 * h), int(0.85 * h)
        self._gaps_this_pass: set[int] = set()
        self._last_progress = 0.0
        # GPU pass: recognized products confirm a section is stocked even when
        # its edge density is low (plain packaging), cutting false gaps.
        self.coco = get_coco_model()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        progress = (timestamp_s % self.period_s) / self.period_s
        if progress < self._last_progress:  # wrapped -> new pass
            self._gaps_this_pass.clear()
        self._last_progress = progress
        sweep_x = int(progress * self.w)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        products = detect(self.coco, frame, classes=list(GROCERY_CLASSES))
        draw_detections(frame, products, BRAND_FRESH)
        product_xs = [float(x1 + x2) / 2 for x1, _, x2, _ in products.xyxy]

        col_w = self.w // self.cols
        for c in range(self.cols):
            cx0 = c * col_w
            cx1 = self.w if c == self.cols - 1 else (c + 1) * col_w
            scanned = (cx0 + cx1) // 2 <= sweep_x
            if not scanned:
                continue
            mask = np.zeros(gray.shape, np.uint8)
            mask[self.y0:self.y1, cx0:cx1] = 255
            dens = edge_density(gray, mask)
            has_product = any(cx0 <= px < cx1 for px in product_xs)
            gap = dens < self.gap_threshold and not has_product
            color = BRAND_RED if gap else BRAND_GREEN
            if gap:
                self._gaps_this_pass.add(c)
            cv2.rectangle(frame, (cx0 + 2, self.y0), (cx1 - 2, self.y1), color, 2)
            if gap:
                cv2.putText(frame, "GAP", (cx0 + 6, self.y0 + 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, BRAND_RED, 2, cv2.LINE_AA)

        cv2.line(frame, (sweep_x, self.y0), (sweep_x, self.y1), BRAND_CYAN, 3)
        headline = f"Robot scan {int(progress*100)}%  ·  gaps found: {len(self._gaps_this_pass)}"
        draw_banner(frame, headline, alert=len(self._gaps_this_pass) > 0)
        metrics = {"scan_progress_pct": int(progress * 100),
                   "sections": self.cols,
                   "gaps_found": len(self._gaps_this_pass),
                   "products_recognized": len(products)}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
