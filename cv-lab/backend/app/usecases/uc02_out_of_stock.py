"""UC-2: Real-Time Shelf Out-of-Stock Detection.

Per shelf zone we estimate occupancy and raise a replenishment alert when it
drops below a threshold. Strategies (in priority order):

* Empty-shelf model: a purpose-trained detector (e.g. Roboflow Universe
  "empty-slots-in-shelves" weights). Occupancy = 1 - (empty area / zone area).
* COCO product detection (GPU): when no specialty weights are configured but a
  GPU is present, the COCO detector runs on the GPU to locate on-shelf products
  (bottles, produce, packaged goods). This both drives real GPU inference and
  yields a per-zone item count shown on the overlay. Occupancy still uses the
  edge-density heuristic, which is robust to boxed goods COCO can't classify.
* Heuristic fallback (CPU only): assume the first frame shows a full shelf and
  track edge/texture density per zone; occupancy = current_density / baseline.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import device as resolved_device
from app.core.models import get_coco_model, get_empty_shelf_model
from app.core.tracking import detections_from_yolo
from app.schemas import AnalysisConfig

from .base import (BRAND_FRESH, BRAND_GREEN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer,
                   draw_banner, polygons_to_pixels, progress_bar, register)

# COCO classes that plausibly appear as shelf products (bottles, tableware,
# produce, packaged food, and a few household goods). Used to keep the overlay
# focused on merchandise rather than people/fixtures.
_PRODUCT_CLASSES = {
    39, 40, 41, 42, 43, 44, 45,                  # bottle, wine glass, cup, fork, knife, spoon, bowl
    46, 47, 48, 49, 50, 51, 52, 53, 54, 55,      # banana .. cake (produce / food)
    73, 75, 76, 77, 79,                          # book, vase, scissors, teddy bear, toothbrush
}


def _zone_mask(shape, polygon) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)
    return mask


def _edge_density(gray: np.ndarray, mask: np.ndarray) -> float:
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.bitwise_and(edges, edges, mask=mask)
    area = max(1, int(np.count_nonzero(mask)))
    return float(np.count_nonzero(edges)) / area


@register
class OutOfStockAnalyzer(UseCaseAnalyzer):
    id = "uc-02"
    title = "Real-Time Shelf Out-of-Stock Detection"
    pattern = "shelf-vision"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.threshold: float = float(config.params.get("threshold", 0.5))
        self.model = get_empty_shelf_model()
        self.use_model = self.model is not None

        # When no specialty empty-shelf weights are present, run the COCO product
        # detector on the GPU so the use case performs real accelerated inference
        # (and the GPU utilization meter reflects it). Skipped on CPU-only nodes
        # to keep the heuristic path fast.
        self.coco = None
        if not self.use_model and resolved_device().startswith("cuda"):
            try:
                self.coco = get_coco_model()
            except Exception:  # noqa: BLE001
                self.coco = None

        zones = polygons_to_pixels(config, w, h)
        if not zones:
            # Default: split the frame into three vertical shelf bays.
            zones = []
            for i in range(3):
                x0 = int((0.05 + i * 0.30) * w)
                x1 = int((0.32 + i * 0.30) * w)
                pts = np.array([[x0, int(0.15 * h)], [x1, int(0.15 * h)],
                                [x1, int(0.9 * h)], [x0, int(0.9 * h)]], dtype=np.int32)
                zones.append((f"Bay {i+1}", pts))
        self.zones = zones

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Baseline density per zone for the heuristic strategy.
        self.baseline = {name: max(1e-4, _edge_density(gray, _zone_mask(frame.shape, pts)))
                         for name, pts in self.zones}
        self.masks = {name: _zone_mask(frame.shape, pts) for name, pts in self.zones}

    def _occupancy_model(self, frame: np.ndarray) -> dict[str, float]:
        """Occupancy per zone from empty-shelf detections."""
        result = self.model(frame, verbose=False)[0]
        dets = detections_from_yolo(result)
        empty = np.zeros((self.h, self.w), dtype=np.uint8)
        for box in dets.xyxy:
            x1, y1, x2, y2 = [int(v) for v in box]
            cv2.rectangle(empty, (x1, y1), (x2, y2), 255, -1)
        occ = {}
        for name, mask in self.masks.items():
            zone_area = max(1, int(np.count_nonzero(mask)))
            empty_in_zone = int(np.count_nonzero(cv2.bitwise_and(empty, empty, mask=mask)))
            occ[name] = max(0.0, 1.0 - empty_in_zone / zone_area)
        return occ

    def _occupancy_heuristic(self, frame: np.ndarray) -> dict[str, float]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        occ = {}
        for name, mask in self.masks.items():
            density = _edge_density(gray, mask)
            occ[name] = max(0.0, min(1.0, density / self.baseline[name]))
        return occ

    def _detect_products(self, frame: np.ndarray) -> list[tuple[int, int, int, int, int, int]]:
        """GPU COCO inference -> product boxes as (cx, cy, x1, y1, x2, y2)."""
        result = self.coco(frame, verbose=False)[0]
        dets = detections_from_yolo(result, allowed_classes=_PRODUCT_CLASSES)
        out: list[tuple[int, int, int, int, int, int]] = []
        for box in dets.xyxy:
            x1, y1, x2, y2 = [int(v) for v in box]
            out.append(((x1 + x2) // 2, (y1 + y2) // 2, x1, y1, x2, y2))
        return out

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        occ = self._occupancy_model(frame) if self.use_model else self._occupancy_heuristic(frame)

        # GPU product detection: visualize merchandise and count items per zone.
        items = {name: 0 for name, _ in self.zones}
        if self.coco is not None:
            for (cx, cy, x1, y1, x2, y2) in self._detect_products(frame):
                cv2.rectangle(frame, (x1, y1), (x2, y2), BRAND_ORANGE, 1, cv2.LINE_AA)
                for name, pts in self.zones:
                    if cv2.pointPolygonTest(pts, (float(cx), float(cy)), False) >= 0:
                        items[name] += 1
                        break

        low_zones = [name for name, v in occ.items() if v < self.threshold]
        alert = len(low_zones) > 0

        for (name, pts) in self.zones:
            v = occ.get(name, 1.0)
            color = BRAND_RED if v < self.threshold else BRAND_GREEN
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], color)
            cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
            cv2.polylines(frame, [pts], True, color, 2)
            x, y = int(pts[:, 0].min()), int(pts[:, 1].min())
            label = f"{name}: {int(v * 100)}%"
            if self.coco is not None:
                label += f"  {items.get(name, 0)} items"
            cv2.putText(frame, label, (x + 4, max(18, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, color, 2, cv2.LINE_AA)
            progress_bar(frame, v, (x + 4, max(20, y - 4) + 2), 120, 10,
                         color=BRAND_FRESH, warn_below=self.threshold)

        if self.use_model:
            strategy = "model"
        elif self.coco is not None:
            strategy = "yolo-coco + density (GPU)"
        else:
            strategy = "heuristic"
        if alert:
            headline = f"REPLENISH: {', '.join(low_zones)}"
        else:
            headline = f"Shelves stocked  ·  occupancy OK ({strategy})"
        draw_banner(frame, headline, alert=alert)

        metrics = {
            "strategy": strategy,
            "threshold": self.threshold,
            "occupancy": {k: round(v, 3) for k, v in occ.items()},
            "low_zones": low_zones,
        }
        if self.coco is not None:
            metrics["items"] = items
            metrics["items_total"] = int(sum(items.values()))
        return frame, {"status": "alert" if alert else "ok", "headline": headline, "values": metrics}
