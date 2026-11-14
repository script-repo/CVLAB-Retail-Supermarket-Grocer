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

import hashlib
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
    int8: bool = False          # INT8 (OpenVINO, detect models only)


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
            int8, why = _want_int8()
            return RuntimePlan(dev, "openvino", False, "CPU + OpenVINO installed" + why, int8=int8)
        if _has_module("onnxruntime") and _has_module("onnx"):
            return RuntimePlan(dev, "onnx", False, "CPU + ONNX Runtime installed")
        return RuntimePlan(dev, "pytorch", False, "CPU; no accelerated runtime installed")
    return RuntimePlan(dev, "pytorch", False, f"device {dev}")


def _cpu_has_bf16() -> bool:
    try:
        import openvino as ov

        return "BF16" in ov.Core().get_property("CPU", "OPTIMIZATION_CAPABILITIES")
    except Exception:  # noqa: BLE001
        return False


def _cpu_has_vnni() -> bool | None:
    """True/False from the CPU flags (VNNI = hardware INT8 dot products), or
    None when the flags can't be read (non-Linux)."""
    try:
        flags = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None
    return "avx512_vnni" in flags or "avx_vnni" in flags


def _want_int8() -> tuple[bool, str]:
    mode = (get_settings().model_int8 or "auto").strip().lower()
    if mode in ("false", "0", "no", "off"):
        return False, ""
    if not _has_module("nncf"):
        if mode != "auto":
            logger.warning("MODEL_INT8=%s but nncf is not installed; using FP32", mode)
        return False, ""
    if mode == "auto":
        if _cpu_has_bf16():
            return False, " (BF16-capable CPU: FP32 models already run in BF16; INT8 skipped)"
        if not _cpu_has_vnni():
            # Without VNNI, INT8 gains are small or negative: stay on FP32.
            return False, " (CPU without VNNI: INT8 skipped)"
    return True, " + INT8"


def _calibration_yaml(names) -> Path | None:
    """Build a small calibration dataset (YOLO yaml) from CALIB_DIR images, or
    frames sampled from stored / bundled videos. None if too few frames."""
    import cv2
    import yaml

    s = get_settings()
    out = (s.export_dir or (s.models_dir / "exported")) / "calibration"
    img_dir = out / "images"
    exts = (".jpg", ".jpeg", ".png")
    if s.calib_dir and len([p for p in s.calib_dir.glob("*") if p.suffix.lower() in exts]) >= 16:
        root, rel = s.calib_dir, "."
    else:
        if not (img_dir.is_dir() and len(list(img_dir.glob("*.jpg"))) >= 16):
            videos = sorted(Path(s.local_storage_dir).rglob("*.mp4"))
            bundled = Path(__file__).resolve().parents[4] / "video-assets"
            videos += sorted(bundled.glob("*.mp4")) if bundled.is_dir() else []
            if not videos:
                return None
            img_dir.mkdir(parents=True, exist_ok=True)
            per = max(1, s.calib_frames // len(videos))
            for v in videos[: s.calib_frames]:
                cap = cv2.VideoCapture(str(v))
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
                for k in range(per):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * n / per))
                    ok, frame = cap.read()
                    if ok:
                        cv2.imwrite(str(img_dir / f"{v.stem}_{k}.jpg"), frame)
            if len(list(img_dir.glob("*.jpg"))) < 16:
                return None
        root, rel = out, "images"
    names = dict(names) if isinstance(names, dict) else dict(enumerate(names))
    cfg = out / "calib.yaml"
    out.mkdir(parents=True, exist_ok=True)
    cfg.write_text(yaml.safe_dump({"path": str(Path(root).resolve()), "train": rel, "val": rel,
                                   "names": names}))
    return cfg


def _engine_tag() -> str:
    """GPU + TensorRT identity: an engine only runs where it was built."""
    try:
        import tensorrt as trt
        import torch

        gpu = torch.cuda.get_device_name(0)
        return re.sub(r"[^A-Za-z0-9]+", "-", f"{gpu}-trt{trt.__version__}").strip("-").lower()
    except Exception:  # noqa: BLE001
        return "unknown"


def _prompt_tag(prompts: tuple[str, ...] | None) -> str:
    if not prompts:
        return ""
    return "-p" + hashlib.sha1("\n".join(prompts).encode()).hexdigest()[:8]


def _export_target(weights: Path, plan: RuntimePlan, imgsz: int,
                   prompts: tuple[str, ...] | None = None) -> Path:
    s = get_settings()
    out_dir = s.export_dir or (s.models_dir / "exported")
    # Prompted (open-vocabulary) models bake their classes in, so the prompt
    # set is part of the cache key.
    stem = (f"{weights.stem}{_prompt_tag(prompts)}-{imgsz}{'-fp16' if plan.half else ''}"
            f"{'-int8' if plan.int8 else ''}")
    if plan.runtime == "tensorrt":
        return out_dir / f"{stem}-{_engine_tag()}.engine"
    if plan.runtime == "openvino":
        return out_dir / f"{stem}_openvino_model"
    return out_dir / f"{stem}.onnx"


def _export(base, weights: Path, plan: RuntimePlan, imgsz: int,
            prompts: tuple[str, ...] | None = None) -> tuple[Path, bool]:
    """Export ``base`` (a loaded .pt YOLO) for ``plan`` and cache the result.

    Returns (path, int8) — INT8 is dropped for non-detect / prompted models
    and when no calibration frames are available."""
    calib = None
    if plan.int8:
        # INT8 needs task-matched calibration data: plain detectors only.
        calib = _calibration_yaml(base.names) if base.task == "detect" and not prompts else None
        if calib is None:
            plan = RuntimePlan(plan.device, plan.runtime, plan.half, plan.reason, int8=False)
    target = _export_target(weights, plan, imgsz, prompts)
    if target.exists():
        return target, plan.int8
    target.parent.mkdir(parents=True, exist_ok=True)
    fmt = _FORMATS[plan.runtime]
    # Ultralytics >=8.4 expresses precision as quantize=16 (FP16) / None (FP32).
    kwargs: dict = {"format": fmt, "imgsz": imgsz, "device": plan.device,
                    "quantize": 8 if plan.int8 else (16 if plan.half else None)}
    if calib is not None:
        kwargs["data"] = str(calib)
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
    return target, plan.int8


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
    prompts: tuple[str, ...] | None = None
    int8: bool = False

    def __call__(self, source, **kwargs):
        return self.model(source, **{**self.predict_kwargs, **kwargs})

    def predict(self, source, **kwargs):
        return self.__call__(source, **kwargs)

    def __getattr__(self, name):
        return getattr(self.model, name)

    def info(self) -> dict:
        out = {"weights": self.weights, "runtime": self.runtime,
               "device": self.device,
               "precision": "int8" if self.int8 else ("fp16" if self.half else "fp32")}
        if self.prompts:
            out["prompts"] = list(self.prompts)
        return out


def _warmup(m: InferenceModel, imgsz: int) -> None:
    dummy = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
    for _ in range(2):
        m(dummy, verbose=False)


def _open_pt(weights: str, prompts: tuple[str, ...] | None):
    """Load .pt weights; for a prompted model, set its text-prompt classes."""
    if not prompts:
        from ultralytics import YOLO

        return YOLO(weights)
    from ultralytics import YOLOE

    model = YOLOE(weights)
    model.set_classes(list(prompts))  # encodes the prompts with MobileCLIP
    return model


def _load_pytorch(weights: str, plan: RuntimePlan, imgsz: int,
                  prompts: tuple[str, ...] | None = None) -> InferenceModel:
    model = _open_pt(weights, prompts)
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
    return InferenceModel(model, "pytorch", device, half, weights, kwargs, prompts)


def load_yolo(name: str, prompts: tuple[str, ...] | None = None) -> InferenceModel:
    """Load (and cache) a YOLO model by weights name/path on the best runtime.

    ``prompts`` turns an open-vocabulary YOLOE checkpoint into a detector for
    those text prompts (class i = prompts[i]); each prompt set is cached and
    exported separately.
    """
    key = name + _prompt_tag(prompts)
    with _lock:
        if key in _cache:
            return _cache[key]
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
                base = _open_pt(weights, prompts)  # downloads bare names on first use
                wpath = Path(base.ckpt_path or weights)
                exported, int8 = _export(base, wpath, plan, imgsz, prompts)
                yolo = YOLO(str(exported), task=base.task)
                # Exported artifacts carry their own precision; only device/imgsz apply.
                model = InferenceModel(yolo, plan.runtime, plan.device, plan.half, weights,
                                       {"device": plan.device, "imgsz": imgsz}, prompts, int8)
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
            model = _load_pytorch(weights, plan, imgsz, prompts)
            _warmup(model, imgsz)
        logger.info("Loaded YOLO '%s' via %s on %s (%s) — %s", name, model.runtime, model.device,
                    model.info()["precision"], plan.reason)
        _cache[key] = model
        return model


def loaded_models() -> list[dict]:
    """Runtime info for every model loaded so far (for the status API)."""
    with _lock:
        return [m.info() for m in _cache.values()]


def warmup_models(prompt_sets: list[list[str]] | None = None) -> None:
    """Load (and, on first run, export) the shared models ahead of time.

    Runs in a background thread at startup: the COCO detector first, then the
    pose model, then each open-vocabulary prompt set. On GPU, every one of
    these may need a TensorRT build of a few minutes.
    """
    try:
        get_person_model()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Model warm-up failed: %s", exc)
    get_pose_model()
    get_sam_model()
    for prompts in prompt_sets or []:
        get_prompted_model(prompts)


def get_person_model():
    return load_yolo(get_settings().person_model)


def get_coco_model():
    """Full 80-class COCO detector (same weights as the person model).

    Used by object/product use-cases that need classes beyond `person`
    (bottles, produce, bags, etc.)."""
    return load_yolo(get_settings().person_model)


def get_prompted_model(prompts: list[str] | tuple[str, ...]):
    """Open-vocabulary detector for the given text prompts, or None.

    Uses ``OPEN_VOCAB_MODEL`` (a YOLOE checkpoint). Returns None when that is
    blank, or when the CLIP tokenizer package is missing (so Ultralytics never
    tries to pip-install it at runtime), or when loading fails; callers keep
    their non-prompted behaviour in that case. Class ``i`` = ``prompts[i]``.
    """
    name = get_settings().open_vocab_model
    if not name or not prompts:
        return None
    if not _has_module("clip"):
        logger.warning("Open-vocabulary model disabled: install clip-anytorch (see requirements.txt)")
        return None
    try:
        return load_yolo(name, tuple(p.strip() for p in prompts if p.strip()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Open-vocabulary model '%s' unavailable: %s", name, exc)
        return None


_visual_cache: dict[str, "InferenceModel"] = {}
_VISUAL_CACHE_MAX = 4


def get_visual_prompt_model(refer_frame: np.ndarray, boxes: list[list[float]], names: list[str]):
    """Open-vocabulary detector for products shown by example, or None.

    ``boxes`` (xyxy pixels in ``refer_frame``) each outline one example; class
    ``i`` = ``names[i]`` (repeat a name to give several examples of one
    product). The visual-prompt embeddings are computed once (~2 s on CPU);
    after that it runs as a normal YOLOE detector. Kept in PyTorch (FP16 on
    GPU): every new set of examples would otherwise need its own export.
    """
    name = get_settings().open_vocab_model
    if not name or not boxes:
        return None
    labels = list(dict.fromkeys(names))  # unique, in order
    cls = np.array([labels.index(n) for n in names])
    h = hashlib.sha1(refer_frame.tobytes())
    h.update(np.asarray(boxes, np.float32).tobytes())
    h.update("\n".join(names).encode())
    key = h.hexdigest()
    with _lock:
        if key in _visual_cache:
            return _visual_cache[key]
        try:
            from ultralytics import YOLOE

            plan = plan_runtime()
            yoloe = YOLOE(name)
            yoloe.predict(refer_frame, refer_image=refer_frame, verbose=False, device=plan.device,
                          visual_prompts={"bboxes": np.asarray(boxes, np.float32), "cls": cls})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Visual-prompt model unavailable: %s", exc)
            return None
        kwargs = {"device": plan.device, "imgsz": get_settings().model_imgsz}
        if plan.half:
            kwargs["quantize"] = 16
        model = InferenceModel(yoloe, "pytorch", plan.device, plan.half, name, kwargs, tuple(labels))
        while len(_visual_cache) >= _VISUAL_CACHE_MAX:
            _visual_cache.pop(next(iter(_visual_cache)))
        _visual_cache[key] = model
        logger.info("Visual-prompt model ready: %s (%d examples)", ", ".join(labels), len(boxes))
        return model


def get_pose_model():
    """Keypoint model (``POSE_MODEL``), or None when blank / unavailable."""
    name = get_settings().pose_model
    if not name:
        return None
    try:
        return load_yolo(name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pose model '%s' unavailable: %s", name, exc)
        return None


def get_sam_model():
    """Segment Anything (``SEG_MODEL``, e.g. ``sam2.1_t.pt``), or None.

    Prompted with points/boxes, so it stays in PyTorch (not exported). Calls
    are not thread-safe; callers serialise them (see UC-16).
    """
    name = get_settings().seg_model
    if not name:
        return None
    key = "sam:" + name
    with _lock:
        if key in _cache:
            return _cache[key]
        try:
            from ultralytics import SAM

            plan = plan_runtime()
            weights = _resolve_weights(name) or name  # prefer MODELS_DIR copy
            model = InferenceModel(SAM(weights), "pytorch", plan.device, False, name,
                                   {"device": plan.device})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Segment model '%s' unavailable: %s", name, exc)
            return None
        logger.info("Loaded segment model '%s' on %s", name, plan.device)
        _cache[key] = model
        return model


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
