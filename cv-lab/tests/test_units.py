"""Fast unit tests: runtime planning, export naming, inference merging, pose maths."""
import numpy as np
import pytest

from app.config import get_settings
from app.core import models as M
from app.usecases import common as C


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _plan(monkeypatch, device="cpu", fmt="auto", mods=()):
    monkeypatch.setenv("DEVICE", device)
    monkeypatch.setenv("MODEL_FORMAT", fmt)
    get_settings.cache_clear()
    monkeypatch.setattr(M, "_has_module", lambda name: name in mods)
    return M.plan_runtime()


def test_cpu_prefers_openvino_then_onnx_then_pytorch(monkeypatch):
    assert _plan(monkeypatch, mods={"openvino"}).runtime == "openvino"
    assert _plan(monkeypatch, mods={"onnx", "onnxruntime"}).runtime == "onnx"
    p = _plan(monkeypatch, mods=set())
    assert (p.runtime, p.half) == ("pytorch", False)


def test_gpu_prefers_tensorrt_fp16(monkeypatch):
    p = _plan(monkeypatch, device="cuda:0", mods={"tensorrt", "openvino"})
    assert (p.runtime, p.half) == ("tensorrt", True)
    p = _plan(monkeypatch, device="cuda:0", mods=set())
    assert (p.runtime, p.half) == ("pytorch", True)


def test_tensorrt_forced_on_cpu_falls_back(monkeypatch):
    assert _plan(monkeypatch, fmt="tensorrt").runtime == "pytorch"


def test_export_names_differ_by_prompt_and_precision(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    get_settings.cache_clear()
    w = tmp_path / "m.pt"
    fp32 = M.RuntimePlan("cpu", "openvino", False)
    a = M._export_target(w, fp32, 640)
    b = M._export_target(w, fp32, 640, ("wet floor sign",))
    c = M._export_target(w, fp32, 640, ("spill",))
    assert len({a, b, c}) == 3 and a.name == "m-640_openvino_model"
    int8 = M.RuntimePlan("cpu", "openvino", False, int8=True)
    assert M._export_target(w, int8, 640).name == "m-640-int8_openvino_model"


class _FakeModel:
    """Returns fixed detections; records the classes/conf it was asked for."""

    def __init__(self):
        self.calls = []

    def __call__(self, frame, classes=None, conf=0.25, verbose=False):
        self.calls.append((classes, conf))
        return ["result"]


def test_detect_groups_one_call_and_per_group_thresholds(monkeypatch):
    import supervision as sv

    det = sv.Detections(xyxy=np.array([[0, 0, 10, 10], [5, 5, 20, 20], [1, 1, 3, 3]], float),
                        confidence=np.array([0.9, 0.32, 0.5]), class_id=np.array([0, 24, 39]))
    monkeypatch.setattr(C, "detections_from_yolo", lambda r: det)
    fake = _FakeModel()
    out = C.detect_groups(fake, None, {"people": ([0], 0.35), "bags": ([24], 0.3), "items": ([39], 0.6)})
    assert len(fake.calls) == 1 and fake.calls[0] == ([0, 24, 39], 0.3)
    assert len(out["people"]) == 1 and len(out["bags"]) == 1 and len(out["items"]) == 0


def _kp(**pts):
    kp = np.zeros((17, 3), float)
    for name, idx in {"ls": 5, "rs": 6, "lw": 9, "rw": 10, "lh": 11, "rh": 12}.items():
        if name in pts:
            kp[idx] = [*pts[name], 0.9]
    return kp


BODY = dict(ls=(90, 100), rs=(110, 100), lh=(92, 200), rh=(108, 200))


def test_pose_arms_down_is_idle():
    kp = _kp(**BODY, lw=(88, 210), rw=(112, 210))
    assert not C.hands_active(kp) and not C.is_reaching(kp)


def test_pose_hands_at_working_height_is_active_not_reaching():
    kp = _kp(**BODY, lw=(95, 150), rw=(112, 210))
    assert C.hands_active(kp) and not C.is_reaching(kp)


def test_pose_reach_up_and_sideways():
    assert C.is_reaching(_kp(**BODY, lw=(90, 80)))          # above shoulders
    assert C.is_reaching(_kp(**BODY, rw=(200, 130)))        # stretched sideways


def test_pose_missing_torso_is_not_active():
    assert not C.hands_active(_kp(lw=(0, 0), rw=(5, 5)))


def _int8(monkeypatch, mode="auto", nncf=True, bf16=False, vnni=True):
    monkeypatch.setenv("MODEL_INT8", mode)
    get_settings.cache_clear()
    monkeypatch.setattr(M, "_has_module", lambda name: nncf if name == "nncf" else True)
    monkeypatch.setattr(M, "_cpu_has_bf16", lambda: bf16)
    monkeypatch.setattr(M, "_cpu_has_vnni", lambda: vnni)
    return M._want_int8()[0]


def test_int8_auto_only_with_vnni_and_without_amx(monkeypatch):
    assert _int8(monkeypatch) is True                      # VNNI, no AMX: faster
    assert _int8(monkeypatch, bf16=True) is False          # AMX: FP32 already runs as BF16
    assert _int8(monkeypatch, vnni=False) is False         # no VNNI: little/no gain
    assert _int8(monkeypatch, vnni=None) is False          # unknown CPU: stay safe
    assert _int8(monkeypatch, nncf=False) is False         # extra not installed


def test_int8_explicit_modes(monkeypatch):
    assert _int8(monkeypatch, mode="true", bf16=True, vnni=False) is True
    assert _int8(monkeypatch, mode="false") is False
