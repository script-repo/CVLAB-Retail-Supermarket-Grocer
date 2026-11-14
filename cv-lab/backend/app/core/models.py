"""Model registry, lazy loader and hardware-aware inference runtime.

Wraps Ultralytics YOLO so use-cases request a model by role
(``person``, ``empty_shelf``, ``spill``) without caring where the weights live
or which runtime executes them. Models are loaded once and cached. Optional
weights (empty shelf / spill) are only loaded if a path is configured;
otherwise the use-case uses its heuristic fallback.

Runtime selection (``MODEL_FORMAT=auto``, the default)
------------------------------------------------------
The same code and settings work on GPU and CPU-only deployments; the fastest
runtime available on the hardware is picked at load time:

* **NVIDIA GPU** -> TensorRT engine in FP16 when the ``tensorrt`` package is
  installed (see ``requirements-gpu.txt``), otherwise PyTorch on CUDA in FP16.
* **CPU only**   -> OpenVINO IR (FP32) when ``openvino`` is installed (it is in
  ``requirements.txt``), otherwise ONNX Runtime if present, otherwise PyTorch.

Exports are built once from the ``.pt`` weights and cached under
``EXPORT_DIR`` (default ``<MODELS_DIR>/exported``). TensorRT engines are tied
to the GPU model and TensorRT version, so both are part of the cache name and a
different GPU simply triggers a fresh build. Any export/load failure falls back
to plain PyTorch on the same device, so a missing accelerator package can slow
inference down but never break it.

In ``auto`` mode a runtime is only chosen when its Python package is already
importable, so Ultralytics never pip-installs packages at runtime.
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

_cache: dict[str, "InferenceModel"] = {}
_lock = threading.RLock()

# MODEL_FORMAT value -> Ultralytics export format.
_FORMATS = {
    "pytorch": None,
    "tensorrt": "engine",
    "engine": "engine",
    "openvino": "openvino",
    "onnx": "onnx",
}


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_weights(name: str) -> str | None:
    """Resolve a weights name to a path. Ultralytics auto-downloads bare COCO
    names like ``yolo11n.pt`` on first use, so those pass through unchanged."""
    if not name:
        return None
    settings = get_settings()
    candidate = settings.models_dir / name
    if candidate.exists():
        return str(candidate)
    # Bare ultralytics names (e.g. yolo11n.pt) are downloaded on demand.
    if Path(name).suffix == ".pt" and "/" not in name and "\\" not in name:
        return name
    if Path(name).exists():
        return name
    logger.warning("Weights '%s' not found under %s; role disabled", name, settings.models_dir)
    return None


# --------------------------------------------------------------------------
# Runtime planning
# --------------------------------------------------------------------------
@dataclass
class RuntimePlan:
    device: str                 # "cuda:0" | "cpu" | "mps" ...
    runtime: str                # "tensorrt" | "openvino" | "onnx" | "pytorch"
    half: bool                  # FP16 inference
    reason: str = ""


def plan_runtime() -> RuntimePlan:
    """Decide device, runtime and precision from settings + detected hardware."""
    s = get_settings()
    dev = _resolve_device(s.device)
    on_cuda = dev.startswith("cuda")
    requested = (s.model_format or "auto").strip().lower()
    # FP16 only pays off (and is only supported) on CUDA.
    half = on_cuda if s.model_fp16 is None else (bool(s.model_fp16) and on_cuda)

    if requested != "auto":
        if requested not in _FORMATS:
            logger.warning("Unknown MODEL_FORMAT '%s'; using auto", requested)
        else:
            runtime = "tensorrt" if requested == "engine" else requested
            if runtime == "tensorrt" and not on_cuda:
                return RuntimePlan(dev, "pytorch", False, "TensorRT requested but no CUDA device")
            return RuntimePlan(dev, runtime, half, f"MODEL_FORMAT={requested}")

    if on_cuda:
        if _has_module("tensorrt"):
            return RuntimePlan(dev, "tensorrt", half, "CUDA GPU + TensorRT installed")
        return RuntimePlan(dev, "pytorch", half, "CUDA GPU; TensorRT not installed")
    if dev == "cpu":
        if _has_module("openvino"):
            return RuntimePlan(dev, "openvino", False, "CPU + OpenVINO installed")
        if _has_module("onnxruntime") and _has_module("onnx"):
            return RuntimePlan(dev, "onnx", False, "CPU + ONNX Runtime installed")
        return RuntimePlan(dev, "pytorch", False, "CPU; no accelerated runtime installed")
    return RuntimePlan(dev, "pytorch", False, f"device {dev}")


def _engine_tag() -> str:
    """GPU + TensorRT identity: an engine only runs where it was built."""
    try:
        import tensorrt as trt
        import torch

        gpu = torch.cuda.get_device_name(0)
        return re.sub(r"[^A-Za-z0-9]+", "-", f"{gpu}-trt{trt.__version__}").strip("-").lower()
    except Exception:  # noqa: BLE001
        return "unknown"


def _export_target(weights: Path, plan: RuntimePlan, imgsz: int) -> Path:
    s = get_settings()
    out_dir = s.export_dir or (s.models_dir / "exported")
    stem = f"{weights.stem}-{imgsz}{'-fp16' if plan.half else ''}"
    if plan.runtime == "tensorrt":
        return out_dir / f"{stem}-{_engine_tag()}.engine"
    if plan.runtime == "openvino":
        return out_dir / f"{stem}_openvino_model"
    return out_dir / f"{stem}.onnx"


def _export(base, weights: Path, plan: RuntimePlan, imgsz: int) -> Path:
    """Export ``base`` (a loaded .pt YOLO) for ``plan`` and cache the result."""
    target = _export_target(weights, plan, imgsz)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = _FORMATS[plan.runtime]
    # Ultralytics >=8.4 expresses precision as quantize=16 (FP16) / None (FP32).
    kwargs: dict = {"format": fmt, "imgsz": imgsz, "device": plan.device,
                    "quantize": 16 if plan.half else None}
    if fmt in ("engine", "onnx"):
        # simplify would require onnxslim + onnxruntime(-gpu); TensorRT does its
        # own graph optimisation, so skip it to avoid surprise installs.
        kwargs["simplify"] = _has_module("onnxslim") and _has_module("onnxruntime")
    logger.info("Exporting %s -> %s (%s); first run only, may take minutes",
                weights.name, plan.runtime, ", ".join(f"{k}={v}" for k, v in kwargs.items()))
    produced = Path(base.export(**kwargs))
    if produced.resolve() != target.resolve():
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        shutil.move(str(produced), str(target))
    return target


@dataclass
class InferenceModel:
    """Callable stand-in for an Ultralytics ``YOLO`` with runtime defaults.

    ``model(frame, classes=..., conf=...)`` behaves exactly like calling the
    YOLO object, with the planned ``device`` / ``half`` / ``imgsz`` filled in.
    Other attributes (``names``, ...) are delegated to the wrapped model.
    """

    model: object
    runtime: str
    device: str
    half: bool
    weights: str
    predict_kwargs: dict = field(default_factory=dict)

    def __call__(self, source, **kwargs):
        return self.model(source, **{**self.predict_kwargs, **kwargs})

    def predict(self, source, **kwargs):
        return self.__call__(source, **kwargs)

    def __getattr__(self, name):
        return getattr(self.model, name)

    def info(self) -> dict:
        return {"weights": self.weights, "runtime": self.runtime,
                "device": self.device, "precision": "fp16" if self.half else "fp32"}


def _warmup(m: InferenceModel, imgsz: int) -> None:
    dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
    for _ in range(2):
        m(dummy, verbose=False)


def _load_pytorch(weights: str, plan: RuntimePlan, imgsz: int) -> InferenceModel:
    from ultralytics import YOLO

    model = YOLO(weights)
    device = plan.device
    try:
        model.to(device)
    except Exception:  # noqa: BLE001
        device = "cpu"
        model.to(device)
    half = plan.half and device.startswith("cuda")
    kwargs = {"device": device, "imgsz": imgsz}
    if half:
        kwargs["quantize"] = 16  # FP16 compute on CUDA
    return InferenceModel(model, "pytorch", device, half, weights, kwargs)


def load_yolo(name: str) -> InferenceModel:
    """Load (and cache) a YOLO model by weights name/path on the best runtime."""
    with _lock:
        if name in _cache:
            return _cache[name]
        from ultralytics import YOLO

        settings = get_settings()
        weights = _resolve_weights(name)
        if weights is None:
            raise FileNotFoundError(f"Weights not available: {name}")
        plan = plan_runtime()
        imgsz = settings.model_imgsz
        model: InferenceModel | None = None

        # Already-exported weights (.engine / _openvino_model / .onnx) load as-is.
        is_pt = Path(weights).suffix == ".pt"
        if plan.runtime != "pytorch" and is_pt:
            try:
                base = YOLO(weights)  # downloads bare names on first use
                wpath = Path(base.ckpt_path or weights)
                exported = _export(base, wpath, plan, imgsz)
                yolo = YOLO(str(exported), task=base.task)
                # Exported artifacts carry their own precision; only device/imgsz apply.
                model = InferenceModel(yolo, plan.runtime, plan.device, plan.half, weights,
                                       {"device": plan.device, "imgsz": imgsz})
                _warmup(model, imgsz)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s runtime unavailable for '%s' (%s); falling back to PyTorch",
                               plan.runtime, name, exc)
                model = None
        elif not is_pt:
            yolo = YOLO(weights)
            model = InferenceModel(yolo, "exported", plan.device, plan.half, weights,
                                   {"device": plan.device, "imgsz": imgsz})

        if model is None:
            model = _load_pytorch(weights, plan, imgsz)
            _warmup(model, imgsz)
        logger.info("Loaded YOLO '%s' via %s on %s (%s) — %s", name, model.runtime, model.device,
                    "fp16" if model.half else "fp32", plan.reason)
        _cache[name] = model
        return model


def loaded_models() -> list[dict]:
    """Runtime info for every model loaded so far (for the status API)."""
    with _lock:
        return [m.info() for m in _cache.values()]


def warmup_default_model() -> None:
    """Load (and, on first run, export) the shared COCO model ahead of time."""
    try:
        get_person_model()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Model warm-up failed: %s", exc)


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
