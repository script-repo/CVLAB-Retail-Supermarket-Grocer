"""UC-16: Spill & Hazard Detection.

Two strategies:

* Model strategy (preferred): a spill / wet-floor detector (e.g. Roboflow
  Universe "wet-floor" / "spill_detector" weights). Detections inside the floor
  ROI are treated as hazards.
* Heuristic fallback (no weights): compare against a clean baseline frame; a
  persistent new region on the floor (appears and stays put) is flagged as a
  spill. An "unattended" dwell timer counts how long it remains before staff
  arrive.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from app.core.models import get_spill_model
from app.core.tracking import detections_from_yolo
from app.schemas import AnalysisConfig

from .base import (BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner,
                   polygons_to_pixels, register)


@register
class SpillAnalyzer(UseCaseAnalyzer):
    id = "uc-16"
    title = "Spill & Hazard Detection"
    pattern = "task-ops"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_spill_model()
        self.use_model = self.model is not None

        self.min_area_frac: float = float(config.params.get("min_area_frac", 0.01))
        self.persist_frames: int = int(config.params.get("persist_frames", max(5, self.fps)))
        self.diff_thresh: int = int(config.params.get("diff_thresh", 35))

        # Floor ROI: drawn polygon, else lower 45% of frame.
        zones = polygons_to_pixels(config, w, h)
        if zones:
            self.roi = zones[0][1]
        else:
            self.roi = np.array([[0, int(0.55 * h)], [w, int(0.55 * h)],
                                 [w, h], [0, h]], dtype=np.int32)
        self.roi_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(self.roi_mask, [self.roi], 255)
        self.roi_area = max(1, int(np.count_nonzero(self.roi_mask)))

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.baseline = cv2.GaussianBlur(gray, (7, 7), 0)

        self.persist = 0
        self.first_seen_s: float | None = None
        self.detected_at: float | None = None

    def _detect_model(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        result = self.model(frame, verbose=False)[0]
        dets = detections_from_yolo(result)
        boxes = []
        for box in dets.xyxy:
            x1, y1, x2, y2 = [int(v) for v in box]
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            if 0 <= cy < self.h and 0 <= cx < self.w and self.roi_mask[cy, cx]:
                boxes.append((x1, y1, x2, y2))
        return boxes

    def _detect_heuristic(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)
        diff = cv2.absdiff(gray, self.baseline)
        _, thresh = cv2.threshold(diff, self.diff_thresh, 255, cv2.THRESH_BINARY)
        thresh = cv2.bitwise_and(thresh, thresh, mask=self.roi_mask)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        min_area = self.min_area_frac * self.roi_area
        for c in contours:
            if cv2.contourArea(c) >= min_area:
                x, y, bw, bh = cv2.boundingRect(c)
                boxes.append((x, y, x + bw, y + bh))
        return boxes

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        boxes = self._detect_model(frame) if self.use_model else self._detect_heuristic(frame)

        # Persistence: a real spill stays put across frames.
        if boxes:
            self.persist += 1
            if self.first_seen_s is None:
                self.first_seen_s = timestamp_s
        else:
            self.persist = max(0, self.persist - 1)
            if self.persist == 0:
                self.first_seen_s = None
                self.detected_at = None

        confirmed = self.persist >= self.persist_frames and bool(boxes)
        if confirmed and self.detected_at is None:
            self.detected_at = self.first_seen_s

        # Draw ROI outline
        cv2.polylines(frame, [self.roi], True, BRAND_ORANGE, 1)

        unattended_s = 0.0
        if confirmed:
            unattended_s = timestamp_s - (self.detected_at or timestamp_s)
            for (x1, y1, x2, y2) in boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), BRAND_RED, 2)
                cv2.putText(frame, "HAZARD", (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, BRAND_RED, 2, cv2.LINE_AA)
            headline = f"SPILL DETECTED — alert nearest associate  ·  unattended {unattended_s:0.0f}s"
        else:
            strategy = "model" if self.use_model else "heuristic"
            headline = f"Floor clear ({strategy})"

        draw_banner(frame, headline, alert=confirmed)

        metrics = {
            "strategy": "model" if self.use_model else "heuristic",
            "hazard": confirmed,
            "regions": len(boxes) if confirmed else 0,
            "unattended_s": round(unattended_s, 1),
            "persist": self.persist,
        }
        return frame, {"status": "alert" if confirmed else "ok", "headline": headline, "values": metrics}
