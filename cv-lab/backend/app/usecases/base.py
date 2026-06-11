"""Use-case analyzer interface, registry, and shared drawing helpers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

import cv2
import numpy as np

from app.schemas import AnalysisConfig

# Brand palette (BGR for OpenCV) -------------------------------------------
BRAND_GREEN = (42, 61, 0)        # #003D2A
BRAND_FRESH = (108, 179, 62)     # #3EB36C
BRAND_RED = (37, 67, 212)        # #D44325
BRAND_ORANGE = (0, 147, 239)     # #EF9300
BRAND_CYAN = (255, 214, 0)       # #00D6FF
BRAND_CREAM = (210, 227, 233)    # #E9E3D2
WHITE = (255, 255, 255)


class UseCaseAnalyzer(ABC):
    """One analyzer per use case.

    Lifecycle: constructed per stream, ``setup`` called once with the first
    frame and the client config, then ``process_frame`` called for every frame.
    ``process_frame`` returns the annotated BGR frame and a metrics dict.
    """

    id: str = ""
    title: str = ""
    pattern: str = ""
    needs_zones: bool = False

    def __init__(self, fps: int = 12):
        self.fps = fps
        self.frame_index = 0

    @abstractmethod
    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None: ...

    @abstractmethod
    def process_frame(self, frame: np.ndarray, timestamp_s: float) -> tuple[np.ndarray, dict[str, Any]]:
        """Return (annotated_frame_bgr, metrics)."""

    # Optional cleanup hook
    def reset(self) -> None:  # noqa: D401
        self.frame_index = 0


# --- Registry --------------------------------------------------------------

_REGISTRY: dict[str, type[UseCaseAnalyzer]] = {}


def register(cls: type[UseCaseAnalyzer]) -> type[UseCaseAnalyzer]:
    _REGISTRY[cls.id] = cls
    return cls


def get_analyzer_cls(usecase_id: str) -> type[UseCaseAnalyzer]:
    if usecase_id not in _REGISTRY:
        raise KeyError(f"Unknown use case '{usecase_id}'. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[usecase_id]


def list_usecases() -> list[dict[str, Any]]:
    return [
        {"id": c.id, "title": c.title, "pattern": c.pattern, "needs_zones": c.needs_zones}
        for c in sorted(_REGISTRY.values(), key=lambda x: x.id)
    ]


# --- Drawing helpers -------------------------------------------------------

# OpenCV's Hershey fonts are ASCII-only; unicode punctuation renders as "??".
# Map the characters we use in headlines to ASCII, then drop anything else.
_ASCII_MAP = {
    "\u00b7": "|",   # middle dot ·
    "\u2014": "-",   # em dash —
    "\u2013": "-",   # en dash –
    "\u2192": "->",  # right arrow →
    "\u2018": "'", "\u2019": "'",  # smart single quotes
    "\u201c": '"', "\u201d": '"',  # smart double quotes
    "\u2026": "...",  # ellipsis …
}


def ascii_safe(text: str) -> str:
    """Make a string safe for cv2.putText (ASCII-only Hershey fonts)."""
    for src, dst in _ASCII_MAP.items():
        text = text.replace(src, dst)
    return text.encode("ascii", "ignore").decode("ascii")


def polygons_to_pixels(config: AnalysisConfig, w: int, h: int) -> list[tuple[str, np.ndarray]]:
    """Convert normalized polygons (0..1) to pixel-space int arrays."""
    out: list[tuple[str, np.ndarray]] = []
    for poly in config.zones:
        if len(poly.points) < 3:
            continue
        pts = np.array([[int(x * w), int(y * h)] for x, y in poly.points], dtype=np.int32)
        out.append((poly.name, pts))
    return out


def draw_banner(frame: np.ndarray, text: str, *, alert: bool = False) -> None:
    """Top status banner in the brand style."""
    h, w = frame.shape[:2]
    color = BRAND_RED if alert else BRAND_GREEN
    bar_h = max(34, h // 14)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), color, -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    scale = bar_h / 48.0
    cv2.putText(frame, ascii_safe(text), (14, int(bar_h * 0.68)), cv2.FONT_HERSHEY_SIMPLEX,
                0.7 * scale, WHITE, max(1, int(2 * scale)), cv2.LINE_AA)


def draw_chip(frame: np.ndarray, text: str, org: tuple[int, int], color=BRAND_GREEN) -> None:
    """A small pill label with text (e.g. counts above a box)."""
    text = ascii_safe(text)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    x, y = org
    cv2.rectangle(frame, (x, y - th - 8), (x + tw + 12, y + 4), color, -1)
    cv2.putText(frame, text, (x + 6, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)


def progress_bar(frame: np.ndarray, frac: float, org: tuple[int, int], width: int,
                 height: int = 14, color=BRAND_FRESH, warn_below: float | None = None) -> None:
    x, y = org
    frac = max(0.0, min(1.0, frac))
    fill_color = color
    if warn_below is not None and frac < warn_below:
        fill_color = BRAND_RED
    cv2.rectangle(frame, (x, y), (x + width, y + height), (220, 220, 220), -1)
    cv2.rectangle(frame, (x, y), (x + int(width * frac), y + height), fill_color, -1)
    cv2.rectangle(frame, (x, y), (x + width, y + height), (120, 120, 120), 1)


# Type alias for factory functions
AnalyzerFactory = Callable[[int], UseCaseAnalyzer]
