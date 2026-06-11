"""UC-20: Dwell-Time / Product Engagement Analysis.

Tracks shoppers (COCO person + ByteTrack) and measures how long each lingers in
a product/display zone. Sustained dwell counts as an "engagement"; brief passes
do not. Reports average dwell and an engagement (conversion proxy) count.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import supervision as sv

from app.core.models import get_person_model
from app.core.tracking import Tracker
from app.schemas import AnalysisConfig

from .base import BRAND_CYAN, BRAND_GREEN, BRAND_ORANGE, UseCaseAnalyzer, draw_banner, draw_chip, register
from .common import PERSON, detect, zones_from_config, rect_pts


@register
class DwellTimeAnalyzer(UseCaseAnalyzer):
    id = "uc-20"
    title = "Dwell-Time / Product Engagement Analysis"
    pattern = "people-tracking"
    needs_zones = True

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        h, w = frame.shape[:2]
        self.w, self.h = w, h
        self.model = get_person_model()
        self.tracker = Tracker(frame_rate=self.fps)
        self.engage_s = float(config.params.get("engage_seconds", 3.0))
        # Support any number of drawn display zones (default to one centre zone).
        self.zones = zones_from_config(config, w, h, rect_pts(0.3, 0.25, 0.7, 0.95, w, h))
        self.zone_objs = [
            sv.PolygonZone(polygon=pts, triggering_anchors=(sv.Position.BOTTOM_CENTER,))
            for _, pts in self.zones
        ]
        self.box = sv.BoxAnnotator(thickness=2)
        self.engaged: set[int] = set()

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        people = detect(self.model, frame, classes=[PERSON])
        people = self.tracker.update(people, timestamp_s)

        # Trigger every zone; a shopper counts as "at display" if in ANY zone.
        per_zone_counts: list[int] = []
        if len(people):
            masks = []
            for z in self.zone_objs:
                m = z.trigger(people)
                masks.append(m)
                per_zone_counts.append(int(z.current_count))
            union = np.any(np.vstack(masks), axis=0) if masks else np.zeros(len(people), dtype=bool)
        else:
            per_zone_counts = [0] * len(self.zone_objs)
            union = np.zeros(0, dtype=bool)
        in_zone = people[union] if len(people) else people

        dwell_vals = []
        if in_zone.tracker_id is not None:
            for b, tid in zip(in_zone.xyxy, in_zone.tracker_id):
                d = self.tracker.dwell_seconds(int(tid))
                dwell_vals.append(d)
                engaged = d >= self.engage_s
                if engaged:
                    self.engaged.add(int(tid))
                col = BRAND_ORANGE if engaged else BRAND_CYAN
                draw_chip(frame, f"#{int(tid)} {d:0.1f}s", (int(b[0]), max(18, int(b[1]))), col)

        # Draw every zone with its label and live count.
        overlay = frame.copy()
        for _, pts in self.zones:
            cv2.fillPoly(overlay, [pts], BRAND_GREEN)
        cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)
        for (name, pts), count in zip(self.zones, per_zone_counts):
            cv2.polylines(frame, [pts], True, BRAND_GREEN, 2)
            draw_chip(frame, f"{name}: {count}", (int(pts[:, 0].min()), max(18, int(pts[:, 1].min()))), BRAND_GREEN)
        frame = self.box.annotate(frame, in_zone)

        avg = sum(dwell_vals) / len(dwell_vals) if dwell_vals else 0.0
        headline = (
            f"At display: {len(in_zone)}  ·  avg dwell {avg:0.1f}s  ·  "
            f"engaged {len(self.engaged)}  ·  zones {len(self.zones)}"
        )
        draw_banner(frame, headline, alert=False)
        metrics = {
            "at_display": len(in_zone),
            "avg_dwell_s": round(avg, 1),
            "engagements": len(self.engaged),
            "engage_threshold_s": self.engage_s,
            "zones": len(self.zones),
            "per_zone": {name: c for (name, _), c in zip(self.zones, per_zone_counts)},
        }
        return frame, {"status": "ok", "headline": headline, "values": metrics}
