"""GPU telemetry endpoint.

Reports live GPU utilization/memory by shelling out to ``nvidia-smi`` (present
in the pod when an ``nvidia.com/gpu`` resource is allocated). Falls back to a
graceful ``available: false`` payload when no GPU is present (e.g. CPU runs),
so the UI can simply show "CPU mode".
"""
from __future__ import annotations

import shutil
import subprocess

from fastapi import APIRouter

from app.config import get_settings
from app.core import perf
from app.core.models import device as resolved_device

router = APIRouter(prefix="/api/gpu", tags=["gpu"])

_QUERY_FIELDS = [
    "name",
    "utilization.gpu",
    "memory.used",
    "memory.total",
    "temperature.gpu",
    "power.draw",
    "power.limit",
]


def _to_float(val: str) -> float | None:
    val = val.strip()
    if not val or val.upper().startswith("N/A"):
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _read_nvidia_smi() -> dict | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(_QUERY_FIELDS)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None

    # First GPU only (this pod is allocated a single device).
    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < len(_QUERY_FIELDS):
        return None

    name = parts[0]
    util = _to_float(parts[1])
    mem_used = _to_float(parts[2])
    mem_total = _to_float(parts[3])
    temp = _to_float(parts[4])
    power = _to_float(parts[5])
    power_cap = _to_float(parts[6])
    mem_pct = (mem_used / mem_total * 100.0) if (mem_used is not None and mem_total) else None

    return {
        "name": name,
        "util_pct": util,
        "mem_used_mb": mem_used,
        "mem_total_mb": mem_total,
        "mem_pct": round(mem_pct, 1) if mem_pct is not None else None,
        "temp_c": temp,
        "power_w": power,
        "power_cap_w": power_cap,
    }


@router.get("")
def gpu_status() -> dict:
    settings = get_settings()
    dev = resolved_device()  # "cuda:0" | "cpu"
    stats = _read_nvidia_smi()
    return {
        "available": stats is not None,
        "in_use": dev.startswith("cuda"),
        "device": dev,
        "configured_device": settings.device,
        "gpu": stats,
        # Active streams with their share of measured processing time; the UI
        # apportions utilization across use cases by these shares (the driver
        # only reports utilization per process, not per use case).
        "streams": perf.snapshot(),
    }
