"""UC-17: Visual Product Search ("find it on the shelf").

Two modes:

* **Search by example** (draw zones): each drawn zone outlines one example of
  a product in the first frame and its zone name names the product. YOLOE uses
  those examples as visual prompts and then finds every matching product in
  later frames — specific SKUs, not just COCO classes (on the bundled shelf
  video, one example each found the salsa jars and the teal chip bags while
  ignoring the black ones). ~2 s one-off setup, then ~65 ms/frame on CPU.
* **COCO fallback** (no zones, or no open-vocabulary model): the most prominent
  product held up to the camera (largest COCO detection) is mapped to an aisle.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_coco_model, get_visual_prompt_model
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, UseCaseAnalyzer, draw_banner, polygons_to_pixels, register
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
    needs_zones = True   # optional: zones = product examples for search-by-example

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_coco_model()
        self.conf = float(config.params.get("match_conf", 0.25))
        self.examples: list[tuple[str, list[int]]] = []
        for name, pts in polygons_to_pixels(config, w, h):
            x1, y1 = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            if x2 - x1 >= 8 and y2 - y1 >= 8:
                self.examples.append(((name or "product").strip(), [int(x1), int(y1), int(x2), int(y2)]))
        self.vp = None
        if self.examples:
            self.vp = get_visual_prompt_model(frame, [b for _, b in self.examples],
                                              [n for n, _ in self.examples])
        self.labels = list(self.vp.prompts) if self.vp is not None else []

    def _process_examples(self, frame: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        r = self.vp(frame, verbose=False, conf=self.conf)[0]
        counts = {n: 0 for n in self.labels}
        best = None
        for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.int().tolist(), r.boxes.cls.int().tolist()):
            name = self.labels[c] if c < len(self.labels) else str(c)
            counts[name] += 1
            cv2.rectangle(frame, (x1, y1), (x2, y2), BRAND_CYAN, 2)
            cv2.putText(frame, name, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        BRAND_CYAN, 2, cv2.LINE_AA)
            area = (x2 - x1) * (y2 - y1)
            if best is None or area > best[0]:
                best = (area, name)
        found = {n: k for n, k in counts.items() if k}
        if found:
            headline = "Found: " + ", ".join(f"{n} x{k}" for n, k in found.items())
            top = best[1]
            aisle = AISLE_MAP.get(top.lower(), "See store directory")
        else:
            headline = "Searching for: " + ", ".join(self.labels)
            top, aisle = None, None
        draw_banner(frame, headline, alert=False)
        metrics = {"mode": "examples", "products": self.labels, "matches": counts,
                   "match": top, "location": aisle, "candidates": int(sum(counts.values()))}
        return frame, {"status": "ok", "headline": headline, "values": metrics}

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        if self.vp is not None:
            return self._process_examples(frame)
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
        metrics = {"mode": "coco", "match": match_name, "location": aisle, "candidates": len(items)}
        return frame, {"status": "ok", "headline": headline, "values": metrics}
