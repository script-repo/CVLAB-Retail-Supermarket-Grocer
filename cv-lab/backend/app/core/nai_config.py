"""Runtime NAI endpoint settings saved from the UI.

Environment variables remain the defaults. A value saved from the settings
panel is stored under the local data directory and overrides them, so the
inference endpoint can be changed without restarting the process.

The file contains the API key. It lives in the gitignored data directory.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings

logger = logging.getLogger(__name__)

_FILENAME = "nai-config.json"
_applied = False


def _path() -> Path:
    settings = get_settings()
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings.local_storage_dir / _FILENAME


def _hint(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "••••"
    return "••••" + api_key[-4:]


def _clean_base_url(url: str) -> str:
    url = (url or "").strip()
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    url = url.rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            "Base URL must start with http:// or https://, for example https://your-llm-endpoint/v1"
        )
    return url


def apply_saved() -> None:
    """Load the UI override once and apply it onto the process settings."""
    global _applied
    if _applied:
        return
    path = _path()
    _applied = True
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring unreadable NAI config file: %s", type(exc).__name__)
        return
    if not isinstance(data, dict):
        return
    settings = get_settings()
    base_url = data.get("base_url")
    model = data.get("model")
    api_key = data.get("api_key")
    if isinstance(base_url, str):
        settings.nai_base_url = base_url.strip().rstrip("/")
    if isinstance(model, str) and model.strip():
        settings.nai_model = model.strip()
    if isinstance(api_key, str):
        settings.nai_api_key = api_key
    if isinstance(data.get("use_live_llm"), bool):
        settings.nai_use_live_llm = data["use_live_llm"]


def public_config() -> dict:
    apply_saved()
    settings = get_settings()
    key = settings.nai_api_key or ""
    base_url = (settings.nai_base_url or "").strip()
    return {
        "base_url": base_url,
        "model": settings.nai_model,
        "api_key_set": bool(key),
        "api_key_hint": _hint(key),
        "configured": bool(base_url),
        "use_live_llm": bool(settings.nai_use_live_llm),
    }


def prefer_live_llm() -> bool:
    """True when Agentic Ops should call the endpoint instead of demo data."""
    apply_saved()
    return bool(get_settings().nai_use_live_llm)


def save_config(
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
    use_live_llm: bool | None = None,
) -> dict:
    """Persist an override and update the live settings object.

    Omitted fields keep their current value, so the mode toggle can save
    without rewriting the endpoint or the API key.
    """
    apply_saved()
    settings = get_settings()
    if base_url is not None:
        settings.nai_base_url = _clean_base_url(base_url)
    if model is not None:
        cleaned_model = model.strip()
        settings.nai_model = cleaned_model or settings.nai_model or "llama3-1-8b"
    if clear_api_key:
        settings.nai_api_key = ""
    elif api_key and api_key.strip():
        settings.nai_api_key = api_key.strip()
    if use_live_llm is not None:
        settings.nai_use_live_llm = use_live_llm

    payload = {
        "base_url": settings.nai_base_url,
        "model": settings.nai_model,
        "api_key": settings.nai_api_key,
        "use_live_llm": bool(settings.nai_use_live_llm),
    }
    path = _path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    logger.info(
        "NAI endpoint updated (model=%s, configured=%s, live=%s)",
        settings.nai_model, bool(settings.nai_base_url), bool(settings.nai_use_live_llm),
    )
    return public_config()
