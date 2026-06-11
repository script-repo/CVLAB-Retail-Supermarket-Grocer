"""REST API for uploading, listing, retrieving, and deleting videos.

Videos and their metadata/thumbnails are persisted to object storage
(Nutanix Objects / MinIO) so they can be reused across analysis sessions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import cv2
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.config import get_settings
from app.core.storage import (get_storage, iter_meta_keys, meta_key,
                              result_key, thumb_key, video_key)
from app.schemas import VideoList, VideoMeta

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_meta(video_id: str, filename: str, size: int) -> VideoMeta:
    """Probe a stored video and generate + persist a thumbnail."""
    storage = get_storage()
    path = storage.get_path(video_key(video_id))
    cap = cv2.VideoCapture(str(path))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0.0

    ok, frame = cap.read()
    cap.release()
    thumb_url = None
    if ok:
        h, w = frame.shape[:2]
        if w > 480:
            frame = cv2.resize(frame, (480, int(h * 480 / w)))
        ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok2:
            storage.put_bytes(thumb_key(video_id), buf.tobytes(), "image/jpeg")
            thumb_url = f"/api/videos/{video_id}/thumb"

    return VideoMeta(
        id=video_id, filename=filename, size_bytes=size,
        width=width, height=height, fps=round(fps, 2),
        frame_count=frame_count, duration_s=round(duration, 2),
        created_at=_now_iso(), thumb_url=thumb_url,
    )


@router.post("", response_model=VideoMeta)
async def upload_video(file: UploadFile = File(...)) -> VideoMeta:
    settings = get_settings()
    data = await file.read()
    size = len(data)
    if size == 0:
        raise HTTPException(400, "Empty file")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB limit")
    if file.content_type and not file.content_type.startswith("video/"):
        raise HTTPException(415, f"Unsupported content type: {file.content_type}")

    video_id = uuid.uuid4().hex[:12]
    storage = get_storage()
    storage.put_bytes(video_key(video_id), data, file.content_type or "video/mp4")

    meta = _build_meta(video_id, file.filename or f"{video_id}.mp4", size)
    storage.put_json(meta_key(video_id), meta.model_dump())
    return meta


@router.get("", response_model=VideoList)
def list_videos() -> VideoList:
    storage = get_storage()
    videos: list[VideoMeta] = []
    for key in iter_meta_keys(storage):
        try:
            videos.append(VideoMeta(**storage.get_json(key)))
        except Exception:  # noqa: BLE001
            continue
    videos.sort(key=lambda v: v.created_at, reverse=True)
    return VideoList(videos=videos)


@router.get("/{video_id}", response_model=VideoMeta)
def get_video(video_id: str) -> VideoMeta:
    storage = get_storage()
    if not storage.exists(meta_key(video_id)):
        raise HTTPException(404, "Video not found")
    return VideoMeta(**storage.get_json(meta_key(video_id)))


@router.get("/{video_id}/thumb")
def get_thumb(video_id: str) -> Response:
    storage = get_storage()
    if not storage.exists(thumb_key(video_id)):
        raise HTTPException(404, "Thumbnail not found")
    return Response(storage.get_bytes(thumb_key(video_id)), media_type="image/jpeg")


@router.get("/{video_id}/file")
def get_file(video_id: str) -> StreamingResponse:
    storage = get_storage()
    if not storage.exists(video_key(video_id)):
        raise HTTPException(404, "Video not found")
    path = storage.get_path(video_key(video_id))

    def _iter():
        with open(path, "rb") as fh:
            while chunk := fh.read(1024 * 256):
                yield chunk

    return StreamingResponse(_iter(), media_type="video/mp4")


@router.delete("/{video_id}")
def delete_video(video_id: str) -> dict:
    storage = get_storage()
    if not storage.exists(meta_key(video_id)):
        raise HTTPException(404, "Video not found")
    storage.delete_prefix(video_key(video_id))
    storage.delete_prefix(meta_key(video_id))
    storage.delete_prefix(thumb_key(video_id))
    storage.delete_prefix(f"results/{video_id}/")
    return {"deleted": video_id}
