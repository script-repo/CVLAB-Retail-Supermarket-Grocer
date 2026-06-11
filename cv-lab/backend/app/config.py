"""Application settings.

All values are environment-overridable (prefix ``CVLAB_`` or plain names below).
Storage defaults target a local MinIO for development; point them at Nutanix
Objects for production by setting S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Retail-Supermarket-Grocery CV Live-Analysis"
    cors_origins: str = "*"

    # --- Object storage (S3 / Nutanix Objects) ---
    s3_endpoint: str = "http://localhost:9000"          # Nutanix Objects data-services IP in prod
    s3_region: str = "us-east-1"
    s3_bucket: str = "retail-supermarket-grocery-cv"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_verify_ssl: bool = False
    s3_use_path_style: bool = True                       # required by MinIO and Nutanix Objects

    # Fallback to local disk when S3 is unreachable (dev convenience).
    local_storage_dir: Path = Path("data")
    storage_backend: str = "auto"                        # auto | s3 | local

    # --- Models ---
    models_dir: Path = Path("models")
    person_model: str = "yolov8n.pt"                     # COCO; person class = 0
    empty_shelf_model: str = ""                          # optional .pt for UC-2
    spill_model: str = ""                                # optional .pt for UC-16
    device: str = "auto"                                 # auto | cpu | cuda:0

    # --- LLM inference endpoint (any OpenAI-compatible API) ---
    # e.g. Nutanix Enterprise AI (NAI), vLLM, Ollama, OpenAI. Leave blank to run
    # with the deterministic local fallback (no LLM). Set via env / .env.
    nai_base_url: str = ""                                # e.g. https://your-llm-endpoint/v1
    nai_api_key: str = ""                                # set in .env, never commit
    nai_model: str = "llama3-1-8b"
    nai_verify_ssl: bool = False
    nai_timeout_s: float = 120.0
    # Wall-clock cap for the (large) shift-report generation before it falls
    # back to the instant local briefing. Keeps the report from hanging when
    # the LLM endpoint is decoding slowly.
    report_deadline_s: float = 30.0

    # --- Agentic ops ---
    store_name: str = "Demo Grocery — Main St"
    agent_detect_frames: int = 10                        # sustained alert frames before an event fires
    agent_clear_frames: int = 24                         # sustained ok frames before a clearance fires
    agent_max_steps: int = 8                             # tool-use loop cap per agent run

    # --- Streaming ---
    target_fps: int = 12                                 # server-side throttle for the WS stream
    jpeg_quality: int = 70
    max_stream_width: int = 960                          # downscale large frames before encoding
    max_upload_mb: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
