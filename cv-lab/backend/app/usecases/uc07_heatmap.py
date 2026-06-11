"""UC-7: Customer Traffic Heat Maps & Flow Analytics.

COCO person detection + ByteTrack. Foot positions accumulate into a heatmap
that builds over the loop; movement traces show flow. Reports unique visitors
and a live occupancy count.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_person_model
from app.core.tracking import Tracker, detections_from_yolo
from app.schemas import AnalysisConfig

from .base import BRAND_GREEN, UseCaseAnalyzer, draw_banner, register

PERSON_CLASS = 0


@register
class HeatmapAnalyzer(UseCaseAnalyzer):
    id = "uc-07"
    title = "Customer Traffic Heat Maps & Flow Analytics"
    pattern = "people-tracking"
    needs_zones = False

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_person_model()
        self.tracker = Tracker(frame_rate=self.fps)

        self.opacity: float = float(config.params.get("opacity", 0.55))
        self.decay: float = float(config.params.get("decay", 1.0))  # 1.0 = accumulate forever
        self.radius: int = int(config.params.get("radius", max(18, w // 40)))

        # Accumulator in float32 for smooth buildup.
        self.heat = np.zeros((h, w), dtype=np.float32)
        self.trace_annotator = sv.TraceAnnotator(thickness=2, trace_length=40)
        self.unique_ids: set[int] = set()

    def _accumulate(self, detections: sv.Detections) -> None:
        if len(detections) == 0:
            return
        for box in detections.xyxy:
            cx = int((box[0] + box[2]) / 2)
            cy = int(box[3])  # foot point
            cx = max(0, min(self.w - 1, cx))
            cy = max(0, min(self.h - 1, cy))
            cv2.circle(self.heat, (cx, cy), self.radius, 1.0, -1)

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        result = self.model(frame, verbose=False, classes=[PERSON_CLASS])[0]
        detections = detections_from_yolo(result, allowed_classes={PERSON_CLASS})
        detections = self.tracker.update(detections, timestamp_s)

        if detections.tracker_id is not None:
            self.unique_ids.update(int(t) for t in detections.tracker_id)

        if self.decay < 1.0:
            self.heat *= self.decay
        self._accumulate(detections)

        # Render heatmap overlay
        blur = cv2.GaussianBlur(self.heat, (0, 0), sigmaX=self.radius / 2)
        norm = cv2.normalize(blur, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        mask = (norm > 12)[..., None]
        frame = np.where(mask, cv2.addWeighted(frame, 1 - self.opacity, colored, self.opacity, 0), frame)
        frame = np.ascontiguousarray(frame)

        # Flow traces on top
        frame = self.trace_annotator.annotate(frame, detections)

        live = len(detections)
        headline = f"Live: {live}  ·  Unique visitors: {len(self.unique_ids)}"
        draw_banner(frame, headline, alert=False)

        metrics = {
            "live_count": live,
            "unique_visitors": len(self.unique_ids),
            "frame_index": self.frame_index,
        }
        return frame, {"status": "ok", "headline": headline, "values": metrics}
