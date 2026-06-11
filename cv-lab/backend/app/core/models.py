"""Model registry and lazy loader.

Wraps Ultralytics YOLO so use-cases request a model by role
(``person``, ``empty_shelf``, ``spill``) without caring where the weights live.
Models are loaded once and cached. Optional weights (empty shelf / spill) are
only loaded if a path is configured; otherwise the use-case uses its heuristic
fallback.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_cache: dict[str, object] = {}


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def _resolve_weights(name: str) -> str | None:
    """Resolve a weights name to a path. Ultralytics auto-downloads bare COCO
    names like ``yolov8n.pt`` on first use, so those pass through unchanged."""
    if not name:
        return None
    settings = get_settings()
    candidate = settings.models_dir / name
    if candidate.exists():
        return str(candidate)
    # Bare ultralytics names (e.g. yolov8n.pt) are downloaded on demand.
    if Path(name).suffix == ".pt" and "/" not in name and "\\" not in name:
        return name
    if Path(name).exists():
        return name
    logger.warning("Weights '%s' not found under %s; role disabled", name, settings.models_dir)
    return None


def load_yolo(name: str):
    """Load (and cache) a YOLO model by weights name/path."""
    if name in _cache:
        return _cache[name]
    from ultralytics import YOLO

    settings = get_settings()
    weights = _resolve_weights(name)
    if weights is None:
        raise FileNotFoundError(f"Weights not available: {name}")
    model = YOLO(weights)
    device = _resolve_device(settings.device)
    try:
        model.to(device)
    except Exception:  # noqa: BLE001
        device = "cpu"
        model.to(device)
    logger.info("Loaded YOLO '%s' on %s", name, device)
    _cache[name] = model
    return model


def get_person_model():
    return load_yolo(get_settings().person_model)


def get_coco_model():
    """Full 80-class COCO detector (same weights as the person model).

    Used by object/product use-cases that need classes beyond `person`
    (bottles, produce, bags, etc.)."""
    return load_yolo(get_settings().person_model)


def get_empty_shelf_model():
    name = get_settings().empty_shelf_model
    if not name:
        return None
    try:
        return load_yolo(name)
    except FileNotFoundError:
        return None


def get_spill_model():
    name = get_settings().spill_model
    if not name:
        return None
    try:
        return load_yolo(name)
    except FileNotFoundError:
        return None


def device() -> str:
    return _resolve_device(get_settings().device)
