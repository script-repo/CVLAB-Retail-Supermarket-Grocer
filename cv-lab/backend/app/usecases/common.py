"""Shared helpers for use-case analyzers.

Keeps the individual analyzers small by centralizing COCO class groups,
detection helpers, zone resolution, and simple image heuristics.
"""
from __future__ import annotations

import cv2
import numpy as np
import supervision as sv

from app.core.tracking import detections_from_yolo
from app.schemas import AnalysisConfig

# COCO class id groups (yolov8 default model) ------------------------------
PERSON = 0
BAG_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase"}
PRODUCE_CLASSES = {46: "banana", 47: "apple", 49: "orange", 50: "broccoli", 51: "carrot"}
GROCERY_CLASSES = {
    39: "bottle", 40: "wine glass", 41: "cup", 45: "bowl",
    46: "banana", 47: "apple", 48: "sandwich", 49: "orange",
    50: "broccoli", 51: "carrot", 52: "hot dog", 53: "pizza",
    54: "donut", 55: "cake", 24: "backpack", 26: "handbag",
}
# Mock unit prices for cart/checkout demos (CAD).
MOCK_PRICES = {
    "bottle": 2.49, "wine glass": 8.99, "cup": 1.99, "bowl": 4.99,
    "banana": 0.69, "apple": 1.29, "sandwich": 5.49, "orange": 1.19,
    "broccoli": 2.99, "carrot": 1.49, "hot dog": 3.99, "pizza": 7.99,
    "donut": 1.99, "cake": 9.99,
}


def detect(model, frame: np.ndarray, classes: list[int] | None = None, conf: float = 0.35) -> sv.Detections:
    """Run a YOLO model and return supervision Detections (optionally class-filtered)."""
    if classes is not None:
        result = model(frame, verbose=False, classes=classes, conf=conf)[0]
    else:
        result = model(frame, verbose=False, conf=conf)[0]
    return detections_from_yolo(result)


def draw_detections(frame: np.ndarray, det: sv.Detections, color, *, label: str | None = None,
                    thickness: int = 2) -> None:
    """Draw detection boxes with class-name chips (shared GPU-pass overlay)."""
    for i, box in enumerate(det.xyxy):
        x1, y1, x2, y2 = (int(v) for v in box)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        name = label if label is not None else class_label(det, i)
        cv2.putText(frame, name, (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2, cv2.LINE_AA)


def class_label(det: sv.Detections, i: int) -> str:
    """Best-effort class name for detection i."""
    try:
        if det.data and "class_name" in det.data:
            return str(det.data["class_name"][i])
    except Exception:  # noqa: BLE001
        pass
    cid = int(det.class_id[i]) if det.class_id is not None else -1
    return GROCERY_CLASSES.get(cid, BAG_CLASSES.get(cid, str(cid)))


def zone_from_config(config: AnalysisConfig, w: int, h: int, default_pts: np.ndarray, index: int = 0):
    """Return (name, pixel-polygon) from the config's drawn zones, else a default."""
    if config.zones and len(config.zones) > index and len(config.zones[index].points) >= 3:
        z = config.zones[index]
        pts = np.array([[int(x * w), int(y * h)] for x, y in z.points], dtype=np.int32)
        return z.name, pts
    return "zone", default_pts


def zones_from_config(config: AnalysisConfig, w: int, h: int, default_pts: np.ndarray,
                      default_name: str = "zone") -> list[tuple[str, np.ndarray]]:
    """Return ALL drawn zones as (name, pixel-polygon); falls back to a single default."""
    out: list[tuple[str, np.ndarray]] = []
    for i, z in enumerate(config.zones or []):
        if len(z.points) >= 3:
            pts = np.array([[int(x * w), int(y * h)] for x, y in z.points], dtype=np.int32)
            out.append((z.name or f"Zone {i + 1}", pts))
    if not out:
        out.append((default_name, default_pts))
    return out


def rect_pts(x0f, y0f, x1f, y1f, w, h) -> np.ndarray:
    return np.array([[int(x0f * w), int(y0f * h)], [int(x1f * w), int(y0f * h)],
                     [int(x1f * w), int(y1f * h)], [int(x0f * w), int(y1f * h)]], dtype=np.int32)


def mask_from_poly(shape, polygon) -> np.ndarray:
    m = np.zeros(shape[:2], dtype=np.uint8)
    cv2.fillPoly(m, [polygon], 255)
    return m


def edge_density(gray: np.ndarray, mask: np.ndarray) -> float:
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.bitwise_and(edges, edges, mask=mask)
    area = max(1, int(np.count_nonzero(mask)))
    return float(np.count_nonzero(edges)) / area


def hist_corr(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> float:
    """HSV histogram correlation between two frames within a mask (1.0 = identical)."""
    ha = cv2.calcHist([cv2.cvtColor(a, cv2.COLOR_BGR2HSV)], [0, 1], mask, [30, 32], [0, 180, 0, 256])
    hb = cv2.calcHist([cv2.cvtColor(b, cv2.COLOR_BGR2HSV)], [0, 1], mask, [30, 32], [0, 180, 0, 256])
    cv2.normalize(ha, ha); cv2.normalize(hb, hb)
    return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))


def brown_fraction(bgr_roi: np.ndarray) -> float:
    """Fraction of pixels that look brown/dark (bruising/spoilage proxy)."""
    if bgr_roi.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    # Brown/dark-spot range
    lower = np.array([5, 40, 20]); upper = np.array([25, 255, 130])
    mask = cv2.inRange(hsv, lower, upper)
    return float(np.count_nonzero(mask)) / float(mask.size)


def text_like_regions(gray: np.ndarray, mask: np.ndarray, min_area: int = 60, max_area: int = 4000):
    """Cheap OCR-region proposer: high-gradient small blobs (labels/dates/prices).

    Returns list of (x, y, w, h) candidate text boxes. Used as a stand-in when a
    real OCR model is not loaded."""
    g = cv2.bitwise_and(gray, gray, mask=mask)
    grad = cv2.morphologyEx(g, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5)))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, ww, hh = cv2.boundingRect(c)
        area = ww * hh
        ar = ww / float(hh + 1e-3)
        if min_area <= area <= max_area and 1.5 <= ar <= 12:
            boxes.append((x, y, ww, hh))
    return boxes
