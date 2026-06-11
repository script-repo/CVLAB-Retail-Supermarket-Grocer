"""Object storage abstraction.

Primary backend is S3-compatible (Nutanix Objects / MinIO). A local-filesystem
backend is provided so the app runs with zero infrastructure during development.
The active backend is chosen by ``settings.storage_backend`` (``auto`` probes S3
and falls back to local on failure).
"""
from __future__ import annotations

import json
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def get_path(self, key: str) -> Path:
        """Return a local filesystem path for the object (downloading if needed).

        Useful for OpenCV which needs a seekable file to decode video.
        """

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    # Convenience helpers ---------------------------------------------------
    def put_json(self, key: str, obj: dict) -> None:
        self.put_bytes(key, json.dumps(obj, indent=2).encode("utf-8"), "application/json")

    def get_json(self, key: str) -> dict:
        return json.loads(self.get_bytes(key).decode("utf-8"))


class LocalStorage(StorageBackend):
    """Stores objects under ``settings.local_storage_dir`` mirroring S3 keys."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        return self.root / key

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def get_path(self, key: str) -> Path:
        return self._p(key)

    def delete_prefix(self, prefix: str) -> None:
        target = self._p(prefix)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            for p in self.root.glob(prefix + "*"):
                p.unlink(missing_ok=True)

    def list_keys(self, prefix: str) -> list[str]:
        base = self._p(prefix)
        search_root = base if base.is_dir() else self.root / Path(prefix).parent
        if not search_root.exists():
            return []
        keys = []
        for p in search_root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.root).as_posix()
                if rel.startswith(prefix):
                    keys.append(rel)
        return sorted(keys)

    def exists(self, key: str) -> bool:
        return self._p(key).exists()


class S3Storage(StorageBackend):
    """S3-compatible backend (Nutanix Objects, MinIO, AWS S3)."""

    def __init__(self, settings: Settings):
        import boto3
        from botocore.client import Config as BotoConfig

        self.settings = settings
        self.bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            verify=settings.s3_verify_ssl,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
            ),
        )
        self._cache_dir = Path(settings.local_storage_dir) / "_s3cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception:
            logger.info("Creating bucket %s", self.bucket)
            self._client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def get_path(self, key: str) -> Path:
        local = self._cache_dir / key
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            self._client.download_file(self.bucket, key, str(local))
        return local

    def delete_prefix(self, prefix: str) -> None:
        keys = self.list_keys(prefix)
        if not keys:
            return
        self._client.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": [{"Key": k} for k in keys]},
        )
        # Drop any cached copies too.
        for k in keys:
            (self._cache_dir / k).unlink(missing_ok=True)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            keys.extend(obj["Key"] for obj in resp.get("Contents", []))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return sorted(keys)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return a process-wide storage backend, honoring ``storage_backend``."""
    global _backend
    if _backend is not None:
        return _backend

    settings = get_settings()
    choice = settings.storage_backend.lower()

    if choice == "local":
        _backend = LocalStorage(settings.local_storage_dir)
        logger.info("Storage backend: local (%s)", settings.local_storage_dir)
        return _backend

    if choice in ("s3", "auto"):
        try:
            _backend = S3Storage(settings)
            logger.info("Storage backend: s3 (%s/%s)", settings.s3_endpoint, settings.s3_bucket)
            return _backend
        except Exception as exc:  # noqa: BLE001
            if choice == "s3":
                raise
            logger.warning("S3 unavailable (%s); falling back to local storage", exc)

    _backend = LocalStorage(settings.local_storage_dir)
    logger.info("Storage backend: local (%s)", settings.local_storage_dir)
    return _backend


def reset_storage() -> None:
    """Test/dev helper to clear the cached backend."""
    global _backend
    _backend = None


# Key layout helpers --------------------------------------------------------

def video_key(video_id: str) -> str:
    return f"uploads/{video_id}.mp4"


def meta_key(video_id: str) -> str:
    return f"meta/{video_id}.json"


def thumb_key(video_id: str) -> str:
    return f"thumbs/{video_id}.jpg"


def result_key(video_id: str, usecase: str) -> str:
    return f"results/{video_id}/{usecase}.mp4"


def iter_meta_keys(storage: StorageBackend) -> Iterable[str]:
    return storage.list_keys("meta/")
