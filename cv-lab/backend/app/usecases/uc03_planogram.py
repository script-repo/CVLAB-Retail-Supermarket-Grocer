"""UC-3: Planogram Compliance Verification.

The first frame is treated as the approved planogram. Each shelf zone's live HSV
histogram is compared to that baseline; a large drop in correlation means the
slot deviates (misplaced / missing / wrong product) and is flagged.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_empty_shelf_model
from app.schemas import AnalysisConfig

from .base import BRAND_GREEN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner, register
from .common import hist_corr, mask_from_poly, rect_pts, zone_from_config


@register
class PlanogramAnalyzer(UseCaseAnalyzer):
    id = "uc-03"
    title = "Planogram Compliance Verification"
    pattern = "shelf-vision"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.threshold = float(config.params.get("compliance_threshold", 0.6))
        self.model = get_empty_shelf_model()  # optional; heuristic if None

        zones = []
        if config.zones:
            for i, z in enumerate(config.zones):
                if len(z.points) >= 3:
                    pts = np.array([[int(x * w), int(y * h)] for x, y in z.points], dtype=np.int32)
                    zones.append((z.name or f"Slot {i+1}", pts))
        if not zones:
            for i in range(4):
                x0 = 0.04 + i * 0.24
                zones.append((f"Slot {i+1}", rect_pts(x0, 0.2, x0 + 0.2, 0.85, w, h)))
        self.zones = zones
        self.masks = {n: mask_from_poly(frame.shape, p) for n, p in zones}
        self.baseline = frame.copy()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        scores = {}
        non_compliant = []
        for name, pts in self.zones:
            corr = hist_corr(self.baseline, frame, self.masks[name])
            scores[name] = corr
            ok = corr >= self.threshold
            if not ok:
                non_compliant.append(name)
            color = BRAND_GREEN if ok else BRAND_RED
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
            cv2.polylines(frame, [pts], True, color, 2)
            x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
            cv2.putText(frame, f"{name}: {int(corr*100)}%", (x + 4, max(18, y - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

        alert = len(non_compliant) > 0
        headline = (f"PLANOGRAM DEVIATION: {', '.join(non_compliant)}" if alert
                    else "Planogram compliant")
        draw_banner(frame, headline, alert=alert)
        metrics = {
            "threshold": self.threshold,
            "compliance": {k: round(v, 3) for k, v in scores.items()},
            "deviations": non_compliant,
        }
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
