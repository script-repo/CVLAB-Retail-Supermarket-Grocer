"""UC-16: Spill & Hazard Detection.

Two strategies:

* Model strategy (preferred): a spill / wet-floor detector (e.g. Roboflow
  Universe "wet-floor" / "spill_detector" weights). Detections inside the floor
  ROI are treated as hazards.
* Heuristic fallback (no weights): compare against a clean baseline frame; a
  persistent new region on the floor (appears and stays put) is flagged as a
  spill. An "unattended" dwell timer counts how long it remains before staff
  arrive.

Response tracking (open-vocabulary YOLOE, optional): every few frames a
text-prompted detector looks for a wet-floor sign. A sign next to a confirmed
spill marks it CORDONED and stops the unattended timer (the spill stays an
alert until it is cleaned up). Disabled when no open-vocabulary model is
available; spill detection itself is unchanged.

People are removed from the heuristic's change mask (``exclude_people``, on by
default; the person detector only runs on frames that changed), so shoppers
walking through are no longer counted as spill area.

Spill outline (Segment Anything, opt-in via ``SEG_MODEL``): while a spill is
confirmed, a background worker prompts SAM with the spill box plus its most
interior changed point every ``outline_every_s``. The outline is shown and
``spill_area_frac`` reported only if it passes a sanity check (mostly inside
the changed area, not most of the floor); otherwise the box is kept.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import cv2
import numpy as np

from app.core.models import get_person_model, get_prompted_model, get_sam_model, get_spill_model
from app.core.tracking import detections_from_yolo
from app.schemas import AnalysisConfig

from .base import (BRAND_CYAN, BRAND_ORANGE, BRAND_RED, UseCaseAnalyzer, draw_banner,
                   polygons_to_pixels, register)

from .common import PERSON, detect

SIGN_PROMPTS = ["wet floor sign"]

# One shared worker: SAM is slow on CPU and its predictor is not thread-safe.
_sam_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sam-outline")
_sam_lock = threading.Lock()


def _sam_outline(sam, frame: np.ndarray, box, point) -> np.ndarray | None:
    with _sam_lock:
        r = sam(frame, verbose=False, points=[[point]], labels=[[1]], bboxes=[list(box)])[0]
    if r.masks is None or len(r.masks.data) == 0:
        return None
    return r.masks.data[0].cpu().numpy().astype(bool)


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

        # Wet-floor-sign check (response tracking). Signs are static, so a few
        # checks per second are plenty and keep the CPU cost low.
        prompts = config.params.get("sign_prompts") or SIGN_PROMPTS
        if isinstance(prompts, str):
            prompts = [p for p in prompts.split(",") if p.strip()]
        self.sign_model = get_prompted_model(prompts)
        self.sign_conf: float = float(config.params.get("sign_conf", 0.25))
        self.sign_every: int = max(1, int(config.params.get("sign_every", max(1, self.fps // 3))))
        self.sign_near_frac: float = float(config.params.get("sign_near_frac", 0.15))
        self.signs: list[tuple[int, int, int, int]] = []
        self.cordoned_at: float | None = None

        self.exclude_people = str(config.params.get("exclude_people", True)).lower() not in ("0", "false", "no")
        self.person_model = None
        if self.exclude_people and not self.use_model:
            try:
                self.person_model = get_person_model()
            except Exception:  # noqa: BLE001
                self.person_model = None
        self.change_mask: np.ndarray | None = None

        self.sam = get_sam_model()
        self.outline_every_s: float = float(config.params.get("outline_every_s", 3.0))
        self.outline_min_overlap: float = float(config.params.get("outline_min_overlap", 0.5))
        self.outline_max_frac: float = float(config.params.get("outline_max_frac", 0.25))
        self._outline_job: Future | None = None
        self._outline_last_s: float = -1e9
        self.outline: np.ndarray | None = None      # accepted mask
        self.outline_rejected = 0

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
        if self.person_model is not None and cv2.countNonZero(thresh) > 0:
            # People walking through differ from the clean baseline too.
            for x1, y1, x2, y2 in detect(self.person_model, frame, classes=[PERSON]).xyxy.astype(int):
                px, py = int(0.1 * (x2 - x1)), int(0.05 * (y2 - y1))
                thresh[max(0, y1 - py):y2 + py, max(0, x1 - px):x2 + px] = 0
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        self.change_mask = thresh
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        min_area = self.min_area_frac * self.roi_area
        for c in contours:
            if cv2.contourArea(c) >= min_area:
                x, y, bw, bh = cv2.boundingRect(c)
                boxes.append((x, y, x + bw, y + bh))
        return boxes

    def _detect_signs(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        result = self.sign_model(frame, verbose=False, conf=self.sign_conf)[0]
        return [tuple(int(v) for v in b) for b in result.boxes.xyxy.tolist()]

    def _sign_near(self, boxes: list[tuple[int, int, int, int]]) -> bool:
        """True if any sign overlaps a spill box grown by sign_near_frac of the width."""
        pad = self.sign_near_frac * self.w
        for sx1, sy1, sx2, sy2 in self.signs:
            for x1, y1, x2, y2 in boxes:
                if sx1 <= x2 + pad and sx2 >= x1 - pad and sy1 <= y2 + pad and sy2 >= y1 - pad:
                    return True
        return False

    def _outline_seed(self, boxes):
        """(box, point) for SAM: the largest spill box and its most interior
        changed pixel (distance-transform peak), or None."""
        box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        x1, y1, x2, y2 = box
        if self.change_mask is not None:
            blob = np.zeros_like(self.change_mask)
            blob[y1:y2, x1:x2] = self.change_mask[y1:y2, x1:x2]
            if cv2.countNonZero(blob):
                dist = cv2.distanceTransform(blob, cv2.DIST_L2, 5)
                py, px = np.unravel_index(int(np.argmax(dist)), dist.shape)
                return box, [int(px), int(py)]
        return box, [(x1 + x2) // 2, (y1 + y2) // 2]

    def _accept_outline(self, mask: np.ndarray | None) -> bool:
        """Sanity check: mostly inside the changed area and not most of the floor."""
        if mask is None or not mask.any():
            return False
        area = int(mask.sum())
        if area / self.roi_area > self.outline_max_frac:
            return False
        if self.change_mask is not None:
            inside = int(np.count_nonzero(self.change_mask[mask]))
            if inside / area < self.outline_min_overlap:
                return False
        return True

    def _update_outline(self, frame: np.ndarray, boxes, confirmed: bool, timestamp_s: float) -> None:
        if self.sam is None:
            return
        if not confirmed:
            self.outline = None
            return
        job = self._outline_job
        if job is not None and job.done():
            self._outline_job = None
            try:
                mask = job.result()
            except Exception:  # noqa: BLE001
                mask = None
            if self._accept_outline(mask):
                self.outline = mask
            else:
                self.outline_rejected += 1
        if self._outline_job is None and timestamp_s - self._outline_last_s >= self.outline_every_s:
            box, point = self._outline_seed(boxes)
            self._outline_last_s = timestamp_s
            self._outline_job = _sam_pool.submit(_sam_outline, self.sam, frame.copy(), box, point)

    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        self.frame_index += 1
        boxes = self._detect_model(frame) if self.use_model else self._detect_heuristic(frame)
        if self.sign_model is not None and self.frame_index % self.sign_every == 1 % self.sign_every:
            self.signs = self._detect_signs(frame)

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
                self.cordoned_at = None

        confirmed = self.persist >= self.persist_frames and bool(boxes)
        if confirmed and self.detected_at is None:
            self.detected_at = self.first_seen_s
        self._update_outline(frame, boxes, confirmed, timestamp_s)

        # Draw ROI outline
        cv2.polylines(frame, [self.roi], True, BRAND_ORANGE, 1)

        for (x1, y1, x2, y2) in self.signs:
            cv2.rectangle(frame, (x1, y1), (x2, y2), BRAND_CYAN, 2)
            cv2.putText(frame, "WET FLOOR SIGN", (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, BRAND_CYAN, 2, cv2.LINE_AA)

        unattended_s = 0.0
        response_s = None
        if confirmed:
            if self.cordoned_at is None and self._sign_near(boxes):
                self.cordoned_at = timestamp_s
            end = self.cordoned_at if self.cordoned_at is not None else timestamp_s
            unattended_s = max(0.0, end - (self.detected_at or end))
            if self.outline is not None:
                # SAM outline: tint + contour instead of the rough box.
                tint = frame.copy()
                tint[self.outline] = BRAND_RED
                cv2.addWeighted(tint, 0.35, frame, 0.65, 0, frame)
                cnts, _ = cv2.findContours(self.outline.astype(np.uint8), cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(frame, cnts, -1, BRAND_RED, 2)
                ys, xs = np.nonzero(self.outline)
                cv2.putText(frame, "HAZARD (outline)", (int(xs.min()), max(18, int(ys.min()) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, BRAND_RED, 2, cv2.LINE_AA)
            else:
                for (x1, y1, x2, y2) in boxes:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), BRAND_RED, 2)
                    cv2.putText(frame, "HAZARD", (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, BRAND_RED, 2, cv2.LINE_AA)
            if self.cordoned_at is not None:
                response_s = unattended_s
                headline = (f"SPILL CORDONED — wet-floor sign placed after {response_s:0.0f}s"
                            "  ·  cleanup pending")
            else:
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
            "signs": len(self.signs),
            "cordoned": confirmed and self.cordoned_at is not None,
            "response_s": round(response_s, 1) if response_s is not None else None,
            "sign_check": self.sign_model is not None,
            "outline": self.sam is not None,
            "spill_area_frac": (round(float(self.outline.sum()) / self.roi_area, 3)
                                if confirmed and self.outline is not None else None),
            "outlines_rejected": self.outline_rejected,
        }
        return frame, {"status": "alert" if confirmed else "ok", "headline": headline, "values": metrics}
