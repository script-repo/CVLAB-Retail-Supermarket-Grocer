"""UC-6: Queue Length & Wait-Time Monitoring.

COCO person detection + ByteTrack. A polygon zone defines the queue area; we
count people in the zone, estimate wait time, and raise an "open another lane"
alert when the queue exceeds a threshold.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_person_model
from app.core.tracking import Tracker, detections_from_yolo
from app.schemas import AnalysisConfig

from .base import (BRAND_CYAN, BRAND_FRESH, BRAND_GREEN, UseCaseAnalyzer, draw_banner,
                   draw_chip, polygons_to_pixels, register)

PERSON_CLASS = 0


@register
class QueueAnalyzer(UseCaseAnalyzer):
    id = "uc-06"
    title = "Queue Length & Wait-Time Monitoring"
    pattern = "people-tracking"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_person_model()
        self.tracker = Tracker(frame_rate=self.fps)

        # Tunables
        self.service_time_s: float = float(config.params.get("service_time_s", 25))
        self.queue_limit: int = int(config.params.get("queue_limit", 5))
        self.open_lanes: int = max(1, int(config.params.get("open_lanes", 1)))

        # Queue zone: use the drawn polygon, else default to the lower 60% band.
        zones = polygons_to_pixels(config, w, h)
        if zones:
            self.zone_name, polygon = zones[0]
        else:
            self.zone_name = "Checkout queue"
            polygon = np.array(
                [[int(0.05 * w), int(0.40 * h)], [int(0.95 * w), int(0.40 * h)],
                 [int(0.95 * w), int(0.97 * h)], [int(0.05 * w), int(0.97 * h)]],
                dtype=np.int32,
            )
        self.polygon = polygon
        self.zone = sv.PolygonZone(polygon=polygon, triggering_anchors=(sv.Position.BOTTOM_CENTER,))
        self.box_annotator = sv.BoxAnnotator(thickness=2)
        self.peak = 0

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        result = self.model(frame, verbose=False, classes=[PERSON_CLASS])[0]
        detections = detections_from_yolo(result, allowed_classes={PERSON_CLASS})
        detections = self.tracker.update(detections, timestamp_s)

        in_zone_mask = self.zone.trigger(detections)
        in_zone = detections[in_zone_mask] if len(detections) else detections
        count = int(self.zone.current_count)
        self.peak = max(self.peak, count)

        est_wait_s = count * self.service_time_s / self.open_lanes
        alert = count > self.queue_limit
        headline = (
            f"OPEN ANOTHER LANE — {count} in queue (~{est_wait_s/60:.1f} min wait)"
            if alert else f"Queue: {count}  ·  ~{est_wait_s/60:.1f} min wait"
        )

        # Draw zone
        zone_color = (37, 67, 212) if alert else BRAND_GREEN
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], zone_color)
        cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
        cv2.polylines(frame, [self.polygon], True, zone_color, 2)

        # Draw tracked people
        if len(in_zone):
            frame = self.box_annotator.annotate(frame, in_zone)
            if in_zone.tracker_id is not None:
                for box, tid in zip(in_zone.xyxy, in_zone.tracker_id):
                    x1, y1 = int(box[0]), int(box[1])
                    dwell = self.tracker.dwell_seconds(int(tid))
                    draw_chip(frame, f"#{int(tid)} {dwell:0.0f}s", (x1, max(20, y1)), BRAND_CYAN)

        draw_banner(frame, headline, alert=alert)

        metrics = {
            "count": count,
            "peak": self.peak,
            "estimated_wait_s": round(est_wait_s, 1),
            "estimated_wait_min": round(est_wait_s / 60, 2),
            "queue_limit": self.queue_limit,
            "open_lanes": self.open_lanes,
        }
        status = "alert" if alert else "ok"
        return frame, {"status": status, "headline": headline, "values": metrics}
