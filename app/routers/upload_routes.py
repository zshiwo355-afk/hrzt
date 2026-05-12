"""多文件上传。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.auth import require_auth
from app.config import UPLOAD_META_DIR
from app.services.attachment_service import build_attachment_public, save_attachment_meta_db, save_upload_file

router = APIRouter(tags=["upload"])


@router.post("/api/upload")
async def upload_files(
    request: Request,
    mode: str = Form("text"),
    files: list[UploadFile] = File(...),
):
    user_id = require_auth(request)

    if not files:
        raise HTTPException(status_code=400, detail="没有收到文件。")

    if mode not in {"text", "image", "video"}:
        raise HTTPException(status_code=400, detail="上传模式不正确。")

    uploaded = []

    try:
        for upload in files:
            meta = await save_upload_file(upload)
            save_attachment_meta_db(meta, user_id=user_id, source="upload")

            if mode == "image" and meta["category"] != "image":
                stored_path = Path(str(meta.get("stored_path") or ""))
                if str(stored_path) and stored_path.exists():
                    stored_path.unlink(missing_ok=True)
                oss_key = str(meta.get("oss_key") or "").strip()
                if oss_key:
                    from app.providers import oss as oss_provider

                    oss_provider.delete_object(oss_key)
                meta_path = UPLOAD_META_DIR / f"{meta['id']}.json"
                if meta_path.exists():
                    meta_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail="图片模式只能上传 png、jpg、jpeg、webp 这类参考图。")

            uploaded.append(build_attachment_public(meta))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败：{repr(e)}")

    return {"mode": mode, "attachments": uploaded}
