"""Async client for the NAI (Nutanix Enterprise AI) OpenAI-compatible endpoint.

Thin wrapper over ``/v1/chat/completions`` with tool-calling support. The
endpoint serves vLLM-backed models (e.g. ``llama3-1-8b``) behind the NAI
gateway; auth is a bearer API key.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class NaiError(RuntimeError):
    """Raised when the NAI endpoint returns an error or is unreachable."""


class NaiClient:
    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.nai_base_url.rstrip("/")
        self.model = s.nai_model
        self._headers = {"Authorization": f"Bearer {s.nai_api_key}"}
        self._timeout_s = s.nai_timeout_s
        # Short connect timeout so an unreachable/unresolvable endpoint fails fast
        # (otherwise the UI hangs); generous read timeout for slow token decode.
        timeout = httpx.Timeout(connect=4.0, read=s.nai_timeout_s, write=10.0, pool=4.0)
        self._client = httpx.AsyncClient(verify=s.nai_verify_ssl, timeout=timeout)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 700,
        retries: int = 1,
    ) -> dict[str, Any]:
        """One chat-completion call. Returns the assistant ``message`` dict
        (may contain ``tool_calls``).

        Shared LLM endpoints can have highly variable decode speed, so
        transient timeouts are retried once by default before surfacing a
        NaiError.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        last_err: str = ""
        for attempt in range(retries + 1):
            try:
                resp = await self._client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=self._headers
                )
            except httpx.TimeoutException:
                last_err = f"NAI timeout after {self._timeout_s:.0f}s (attempt {attempt + 1})"
                logger.warning(last_err)
                continue
            except httpx.HTTPError as exc:
                last_err = f"NAI unreachable: {type(exc).__name__}: {exc}"
                logger.warning(last_err)
                continue
            if resp.status_code >= 500:
                last_err = f"NAI HTTP {resp.status_code}: {resp.text[:300]}"
                logger.warning(last_err)
                continue
            if resp.status_code != 200:
                raise NaiError(f"NAI HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            try:
                return data["choices"][0]["message"]
            except (KeyError, IndexError) as exc:
                raise NaiError(f"NAI malformed response: {data}") from exc
        raise NaiError(last_err or "NAI request failed")

    async def ping(self) -> bool:
        """Cheap liveness probe (used by the UI status badge / demo pre-flight)."""
        try:
            msg = await self.chat(
                [{"role": "user", "content": "Reply with OK"}], max_tokens=4, temperature=0.0
            )
            return bool(msg)
        except NaiError as exc:
            logger.warning("NAI ping failed: %s", exc)
            return False

    async def close(self) -> None:
        await self._client.aclose()


_client: NaiClient | None = None


def get_nai_client() -> NaiClient:
    global _client
    if _client is None:
        _client = NaiClient()
    return _client
