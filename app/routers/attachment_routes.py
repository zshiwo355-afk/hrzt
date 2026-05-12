"""附件下载。"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from app.auth import require_auth
from app.config import OSS_UPLOAD_PREFIX
from app.providers import oss as oss_provider
from app.services.attachment_service import read_attachment_meta_any

router = APIRouter(tags=["attachments"])


def _download_headers(filename: str) -> dict[str, str]:
    suffix = Path(str(filename or "")).suffix
    if not suffix or len(suffix) > 12 or any(ord(ch) > 127 for ch in suffix):
        suffix = ""
    encoded_name = quote(Path(str(filename or "attachment")).name or f"attachment{suffix}", safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="attachment{suffix}"; '
            f"filename*=UTF-8''{encoded_name}"
        )
    }


def _plain_error(status_code: int, message: str) -> Response:
    return Response(
        content=message.encode("utf-8"),
        status_code=status_code,
        media_type="text/plain; charset=utf-8",
    )


@router.get("/api/attachments/{attachment_id}")
def get_attachment_file(attachment_id: str, request: Request):
    require_auth(request)

    meta = read_attachment_meta_any(attachment_id)
    if not meta:
        return _plain_error(404, "attachment file not found")

    stored_path = str(meta.get("stored_path") or "").strip()
    stored = Path(stored_path) if stored_path else None
    if stored and stored.is_file():
        try:
            return FileResponse(
                str(stored),
                media_type=meta.get("mime_type") or "application/octet-stream",
                headers=_download_headers(meta.get("original_name") or "attachment"),
            )
        except OSError:
            pass

    oss_key = str(meta.get("oss_key") or "").strip()
    if oss_key:
        body = oss_provider.read_bytes(oss_key)
        if body is not None:
            filename = meta.get("original_name") or "attachment"
            return Response(
                content=body,
                media_type=meta.get("mime_type") or "application/octet-stream",
                headers=_download_headers(filename),
            )

    if oss_key:
        return _plain_error(502, "oss file read failed")
    return _plain_error(404, "attachment file not found")


@router.get("/api/generated-images/{task_id}")
def get_generated_image(task_id: str, request: Request):
    require_auth(request)
    safe_id = "".join(ch for ch in str(task_id or "") if ch.isalnum() or ch in "-_")
    if not safe_id:
        return _plain_error(404, "image not found")
    for suffix, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
        key = f"{OSS_UPLOAD_PREFIX}/generated/images/{safe_id}{suffix}"
        body = oss_provider.read_bytes(key)
        if body is not None:
            return Response(content=body, media_type=mime)
    return _plain_error(404, "image not found")
