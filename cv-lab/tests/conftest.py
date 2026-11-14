"""Shared fixtures. Tests run on CPU with local storage; models are downloaded
(and exported to OpenVINO) on first use, then cached under MODELS_DIR."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "cv-lab" / "backend"
VIDEOS = ROOT / "video-assets"

os.environ.setdefault("DEVICE", "cpu")
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("MODEL_WARMUP", "false")
sys.path.insert(0, str(BACKEND))
