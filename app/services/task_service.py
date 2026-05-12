"""后台任务队列与图片/视频任务执行。"""
from __future__ import annotations

import importlib.util
import inspect
import base64
import uuid
import requests
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.ai_context import reset_ai_request_context, set_ai_request_context
from app.config import (
    IMAGE_EDITS_TIMEOUT_SECONDS,
    IMAGE_TASK_TIMEOUT_SECONDS,
    OSS_PREFIX_TASK_RESULTS,
    OSS_UPLOAD_PREFIX,
    TASKS_DIR,
    TASK_RUNNING_REQUEUE_SECONDS,
    UPLOADS_DIR,
    UPLOAD_META_DIR,
    oss_configured,
)
from app.database_models import Conversation, GenerationTask
from app.logging_config import logger
from app.models import TaskCreateRequest
from app.db import get_session_factory
from app.services import artifact_generation_service, conversation_service, image_service, message_service
from app.services.attachment_service import build_attachment_public, save_attachment_meta_db
from app.providers import oss as oss_provider
from app.services.model_service import image_route_meta
from app.storage import (
    list_task_files,
    load_task_file,
    now_iso,
    safe_json_dump,
    safe_json_load,
    save_task_file,
    task_file_path,
)

task_lock = threading.Lock()
task_worker_started = False
_worker_tasks_dir_logged = False
_task_claim_lock = threading.Lock()

IMAGE_REFERENCE_EDIT_PREFIX = (
    "请以参考图为基础，尽量保留原图主体、构图、光照和质感，只按用户要求做局部修改："
)


def _normalize_image_intent(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"edit_uploaded", "edit_previous", "variation", "new_image"}:
        return raw
    return "new_image"


def _normalize_reference_source(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"uploaded", "previous_generated_image", "none"}:
        return raw
    return "none"


def _image_generation_prompt(task_data: dict) -> str:
    prompt = str(task_data.get("prompt") or "").strip()
    intent = _normalize_image_intent(task_data.get("image_intent"))
    reference_source = _normalize_reference_source(task_data.get("reference_source"))
    if reference_source in {"uploaded", "previous_generated_image"} and intent in {
        "edit_uploaded",
        "edit_previous",
        "variation",
    }:
        if prompt.startswith(IMAGE_REFERENCE_EDIT_PREFIX):
            return prompt
        return f"{IMAGE_REFERENCE_EDIT_PREFIX}{prompt}"
    return prompt


def _task_oss_key(history_user_id: str, task_id: str) -> str:
    return f"{OSS_PREFIX_TASK_RESULTS}/users/{history_user_id}/{task_id}.json"


def _sync_task_oss_snapshot(task_data: dict) -> None:
    """任务终态或任意更新后尝试同步快照到 OSS（失败忽略）。"""
    if not oss_configured():
        return
    uid = task_data.get("history_user_id")
    tid = task_data.get("id")
    if not uid or not tid:
        return
    snap = {
        "id": task_data.get("id"),
        "mode": task_data.get("mode"),
        "status": task_data.get("status"),
        "model": task_data.get("model"),
        "progress_text": task_data.get("progress_text") or "",
        "created_at": task_data.get("created_at"),
        "updated_at": task_data.get("updated_at"),
        "started_at": task_data.get("started_at"),
        "finished_at": task_data.get("finished_at"),
        "error_message": task_data.get("error_message") or "",
        "result": task_data.get("result") or {},
    }
    try:
        oss_provider.write_json(_task_oss_key(str(uid), str(tid)), snap)
    except Exception:
        logger.warning("[task-oss] sync failed task_id=%s", tid, exc_info=True)


def _decode_generated_image_data_url(image_url: str) -> tuple[bytes, str, str] | None:
    raw = str(image_url or "").strip()
    if not raw.startswith("data:image/"):
        return None
    head, sep, b64part = raw.partition(",")
    if not sep or not b64part:
        return None
    mime = "image/png"
    suffix = ".png"
    if ";" in head:
        mime = head[5:].split(";", 1)[0] or mime
    if mime == "image/jpeg":
        suffix = ".jpg"
    elif mime == "image/webp":
        suffix = ".webp"
    try:
        data = base64.b64decode(b64part)
    except Exception:
        return None
    return data, mime, suffix


def _download_generated_image_url(image_url: str) -> tuple[bytes, str, str] | None:
    raw = str(image_url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(raw, timeout=60)
        resp.raise_for_status()
    except Exception:
        logger.warning("[image-result] download generated image url failed url=%s", raw[:200], exc_info=True)
        return None
    content_type = (resp.headers.get("Content-Type") or "image/png").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        return None
    suffix = ".png"
    if content_type == "image/jpeg":
        suffix = ".jpg"
    elif content_type == "image/webp":
        suffix = ".webp"
    return resp.content or b"", content_type, suffix


def _persist_generated_image(image_url: str, task_id: str) -> tuple[str, Optional[dict]]:
    decoded = _decode_generated_image_data_url(image_url)
    if decoded is None:
        decoded = _download_generated_image_url(image_url)
    if decoded is None:
        return image_url, None
    data, mime, suffix = decoded

    attachment_id = uuid.uuid4().hex
    stored_name = f"{attachment_id}{suffix}"
    stored_path = UPLOADS_DIR / stored_name
    stored_path.write_bytes(data)

    storage = "local"
    oss_key = ""
    if oss_configured():
        oss_key = f"{OSS_UPLOAD_PREFIX}/generated/images/{attachment_id}{suffix}"
        if oss_provider.write_bytes(oss_key, data, content_type=mime):
            storage = "oss"

    meta = {
        "id": attachment_id,
        "original_name": f"生成图片-{task_id}{suffix}",
        "stored_name": stored_name,
        "stored_path": str(stored_path),
        "storage": storage,
        "oss_key": oss_key if storage == "oss" else "",
        "suffix": suffix,
        "mime_type": mime,
        "category": "image",
        "size": len(data or b""),
    }
    safe_json_dump(UPLOAD_META_DIR / f"{attachment_id}.json", meta)
    save_attachment_meta_db(meta, task_id=task_id, source="generated_image")
    return f"/api/attachments/{attachment_id}", build_attachment_public(meta)


def _persist_generated_image_to_oss(image_url: str, task_id: str) -> str:
    raw = str(image_url or "").strip()
    if not oss_configured():
        return raw
    decoded = _decode_generated_image_data_url(image_url)
    if decoded is None:
        return raw
    data, mime, suffix = decoded
    key = f"{OSS_UPLOAD_PREFIX}/generated/images/{task_id}{suffix}"
    if not oss_provider.write_bytes(key, data, content_type=mime):
        return image_url
    return f"/api/generated-images/{task_id}"


def _tasks_dir_resolved() -> Path:
    return TASKS_DIR.resolve()


def _error_message_with_tb(exc: BaseException, tb_text: str, max_lines: int = 30) -> str:
    """任务 JSON error_message：异常说明 + traceback 前若干行（不写入整段无限长）。"""
    lines = (tb_text or "").splitlines()
    head = "\n".join(lines[:max_lines])
    return f"{exc!s}\n--- traceback (first {max_lines} lines) ---\n{head}"[:32000]


def _log_task(op: str, task_id: Optional[str], path: Path, extra: str = "") -> None:
    msg = "[task] op=%s task_id=%s path=%s%s" % (
        op,
        task_id or "",
        path,
        (" " + extra) if extra else "",
    )
    logger.info(msg)


def _parse_task_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _dt_to_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _iso_to_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _task_row_to_dict(row: GenerationTask) -> dict:
    return {
        "id": row.id,
        "mode": row.mode,
        "artifact_type": row.artifact_type,
        "status": row.status,
        "model": row.model,
        "reasoning_mode": row.reasoning_mode,
        "prompt": row.prompt,
        "size": row.size,
        "n": row.n,
        "conversation_id": row.conversation_id,
        "assistant_message_id": row.assistant_message_id,
        "attachment_ids": row.attachment_ids_json or [],
        "use_rag": bool(row.use_rag),
        "use_web_search": bool(row.use_web_search),
        "image_mode": row.image_mode,
        "image_intent": row.image_intent or "",
        "reference_source": row.reference_source or "",
        "image_intent_confidence": float(row.image_intent_confidence or 0),
        "summary": row.summary or "",
        "history_messages": row.history_messages_json or [],
        "progress_text": row.progress_text or "",
        "created_at": _dt_to_iso(row.created_at),
        "updated_at": _dt_to_iso(row.updated_at),
        "started_at": _dt_to_iso(row.started_at),
        "finished_at": _dt_to_iso(row.finished_at),
        "error_message": row.error_message or "",
        "result": row.result_json or {},
        "history_user_id": row.history_user_id,
    }


def _save_task_db(task_data: dict) -> None:
    now = datetime.now()
    with get_session_factory()() as db:
        row = db.get(GenerationTask, str(task_data["id"]))
        if row is None:
            row = GenerationTask(id=str(task_data["id"]))
        row.mode = str(task_data.get("mode") or "")
        row.artifact_type = task_data.get("artifact_type") or None
        row.status = str(task_data.get("status") or "queued")
        row.model = str(task_data.get("model") or "")
        row.reasoning_mode = str(task_data.get("reasoning_mode") or "default")
        row.prompt = str(task_data.get("prompt") or "")
        row.size = str(task_data.get("size") or "1024x1024")
        row.n = int(task_data.get("n") or 1)
        row.conversation_id = int(task_data["conversation_id"]) if task_data.get("conversation_id") else None
        row.assistant_message_id = (
            int(task_data["assistant_message_id"]) if task_data.get("assistant_message_id") else None
        )
        row.attachment_ids_json = list(task_data.get("attachment_ids") or [])
        row.history_messages_json = list(task_data.get("history_messages") or [])
        row.result_json = dict(task_data.get("result") or {})
        row.use_rag = bool(task_data.get("use_rag"))
        row.use_web_search = bool(task_data.get("use_web_search"))
        row.image_mode = str(task_data.get("image_mode") or "auto_api_passthrough")
        row.image_intent = _normalize_image_intent(task_data.get("image_intent"))
        row.reference_source = _normalize_reference_source(task_data.get("reference_source"))
        row.image_intent_confidence = str(task_data.get("image_intent_confidence") or 0)
        row.summary = str(task_data.get("summary") or "")
        row.progress_text = str(task_data.get("progress_text") or "")
        row.error_message = str(task_data.get("error_message") or "")
        row.history_user_id = task_data.get("history_user_id") or None
        row.created_at = _iso_to_dt(task_data.get("created_at")) or row.created_at or now
        row.updated_at = _iso_to_dt(task_data.get("updated_at")) or now
        row.started_at = _iso_to_dt(task_data.get("started_at"))
        row.finished_at = _iso_to_dt(task_data.get("finished_at"))
        db.add(row)
        db.commit()


def _load_task_db(task_id: str) -> Optional[dict]:
    with get_session_factory()() as db:
        row = db.get(GenerationTask, str(task_id))
        if not row:
            return None
        return _task_row_to_dict(row)


def _task_timeout_seconds(task_data: dict) -> int:
    if str(task_data.get("mode") or "") != "image":
        return max(1800, int(IMAGE_TASK_TIMEOUT_SECONDS))
    has_refs = bool(task_data.get("attachment_ids") or [])
    if has_refs:
        return max(1, int(IMAGE_EDITS_TIMEOUT_SECONDS))
    return max(1, int(IMAGE_TASK_TIMEOUT_SECONDS))


def expire_stale_task_if_needed(task_data: dict) -> dict:
    status = str(task_data.get("status") or "")
    if status not in {"queued", "running"}:
        return task_data
    timeout_seconds = _task_timeout_seconds(task_data)
    started = _parse_task_dt(task_data.get("started_at")) or _parse_task_dt(task_data.get("created_at"))
    if not started:
        return task_data
    elapsed = (datetime.now() - started).total_seconds()
    grace_seconds = 15
    if elapsed <= timeout_seconds + grace_seconds:
        return task_data
    task_id = str(task_data.get("id") or "")
    message = (
        f"图片生成超时，已等待约 {int(elapsed)} 秒，超过当前超时上限 {timeout_seconds} 秒。"
        if str(task_data.get("mode") or "") == "image"
        else f"任务超时，已等待约 {int(elapsed)} 秒。"
    )
    expired = update_task(
        task_id,
        status="failed",
        progress_text="任务超时。",
        finished_at=now_iso(),
        error_message=message,
        result={},
    )
    if expired:
        _finalize_task_message(expired, error_message=message)
        return expired
    return task_data


def save_task(task_data: dict) -> None:
    tid = task_data.get("id")
    path = task_file_path(str(tid)) if tid is not None else Path()
    _log_task("save_pre", str(tid) if tid is not None else None, path)
    _save_task_db(task_data)
    try:
        with task_lock:
            save_task_file(task_data)
    except Exception:
        logger.warning("[task] legacy json save failed task_id=%s", tid, exc_info=True)

    _sync_task_oss_snapshot(task_data)
    _log_task("save_post", str(tid) if tid is not None else None, path, "db=1 legacy_exists=%s" % path.exists())


def load_task(task_id: str) -> Optional[dict]:
    db_task = _load_task_db(task_id)
    if db_task:
        return expire_stale_task_if_needed(db_task)

    path = task_file_path(task_id)
    exists = path.exists()
    _log_task("load", task_id, path, "exists=%s" % exists)
    if not exists:
        return None
    try:
        with task_lock:
            task_data = load_task_file(task_id)
    except Exception as e:
        logger.warning("[task] load failed task_id=%s path=%s err=%s", task_id, path, repr(e))
        return None
    if task_data:
        try:
            _save_task_db(task_data)
        except Exception:
            logger.warning("[task] legacy task import failed task_id=%s", task_id, exc_info=True)
    return expire_stale_task_if_needed(task_data)


def build_task_public(task_data: dict) -> dict:
    result = task_data.get("result") or {}
    return {
        "id": task_data["id"],
        "mode": task_data["mode"],
        "artifact_type": task_data.get("artifact_type") or None,
        "message_id": task_data.get("assistant_message_id") or None,
        "reasoning_mode": task_data.get("reasoning_mode") or "",
        "status": task_data["status"],
        "progress_text": task_data.get("progress_text") or "",
        "created_at": task_data.get("created_at"),
        "updated_at": task_data.get("updated_at"),
        "started_at": task_data.get("started_at"),
        "finished_at": task_data.get("finished_at"),
        "attachment_ids": task_data.get("attachment_ids") or [],
        "error_message": task_data.get("error_message") or "",
        "image_intent": task_data.get("image_intent") or "",
        "reference_source": task_data.get("reference_source") or "",
        "image_intent_confidence": task_data.get("image_intent_confidence") or 0.0,
        "result": result,
    }


def find_active_task_id_for_message(message_id: int) -> str:
    mid = int(message_id)
    with get_session_factory()() as db:
        rows = (
            db.query(GenerationTask)
            .filter(
                GenerationTask.assistant_message_id == mid,
                GenerationTask.status.in_(["queued", "running"]),
            )
            .order_by(GenerationTask.created_at.desc())
            .limit(1)
            .all()
        )
        if rows:
            return str(rows[0].id)
    for path in reversed(list_task_files()):
        try:
            task_data = safe_json_load(path)
        except Exception:
            continue
        if int(task_data.get("assistant_message_id") or 0) != mid:
            continue
        status = str(task_data.get("status") or "")
        if status in {"queued", "running"}:
            return str(task_data.get("id") or "")
    return ""


def update_task(task_id: str, **patch: Any) -> Optional[dict]:
    path = task_file_path(task_id)
    _log_task("update_pre", task_id, path, "patch_keys=%s" % list(patch.keys()))
    task_data = _load_task_db(task_id)
    if not task_data:
        task_data = load_task_file(task_id)
        if not task_data:
            logger.warning(
                "[task] update_task missing or unreadable task_id=%s path=%s (skip)",
                task_id,
                path,
            )
            return None

    task_data.update(patch)
    task_data["updated_at"] = now_iso()
    _save_task_db(task_data)
    try:
        with task_lock:
            save_task_file(task_data)
    except Exception:
        logger.warning("[task] legacy json update failed task_id=%s", task_id, exc_info=True)

    _sync_task_oss_snapshot(task_data)
    _log_task("update_post", task_id, path, "status=%s db=1" % task_data.get("status"))
    return task_data


def cancel_task(task_id: str) -> Optional[dict]:
    task_data = load_task(task_id)
    if not task_data:
        return None
    status = str(task_data.get("status") or "")
    if status in {"succeeded", "failed", "cancelled"}:
        return task_data
    cancelled = update_task(
        task_id,
        status="cancelled",
        progress_text="任务已停止。",
        finished_at=now_iso(),
        error_message="用户已停止生成。",
        result={},
    )
    if cancelled:
        _finalize_task_message(cancelled, error_message="用户已停止生成。")
    return cancelled


def create_generation_task(
    req: TaskCreateRequest,
    history_user_id: Optional[str] = None,
    artifact_type: Optional[str] = None,
    conversation_id: Optional[int] = None,
    assistant_message_id: Optional[int] = None,
) -> dict:
    import uuid

    task_id = uuid.uuid4().hex

    task_data = {
        "id": task_id,
        "mode": req.mode,
        "artifact_type": (artifact_type or req.artifact_type or "").strip().lower() or None,
        "status": "queued",
        "model": req.model,
        "reasoning_mode": (req.reasoning_mode or "").strip().lower() or "default",
        "prompt": req.prompt,
        "size": req.size or "1024x1024",
        "n": req.n or 1,
        "conversation_id": int(conversation_id) if conversation_id else None,
        "assistant_message_id": int(assistant_message_id) if assistant_message_id else None,
        "attachment_ids": req.attachment_ids or [],
        "use_rag": bool(req.use_rag),
        "use_web_search": bool(req.use_web_search),
        "image_mode": "auto_api_passthrough",
        "image_intent": _normalize_image_intent(req.image_intent),
        "reference_source": _normalize_reference_source(req.reference_source),
        "image_intent_confidence": float(req.image_intent_confidence or 0.0),
        "summary": req.summary or "",
        "history_messages": [item.model_dump() for item in (req.history_messages or [])],
        "progress_text": (
            "任务已提交，正在准备文档结构。"
            if req.mode == "artifact"
            else "任务已提交，正在排队。"
        ),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "error_message": "",
        "result": {},
        "history_user_id": history_user_id,
    }

    save_task(task_data)
    return task_data


def _finalize_task_message(task_data: dict, *, result: Optional[dict] = None, error_message: str = "") -> None:
    message_id = task_data.get("assistant_message_id")
    if not message_id:
        return
    conversation_id = task_data.get("conversation_id")
    try:
        with get_session_factory()() as db:
            if error_message:
                message_service.fail_assistant_message(
                    db,
                    message_id=int(message_id),
                    error_message=error_message,
                )
                return

            final_text = str((result or {}).get("text") or "文件已生成。")
            attachments = None
            image_url = str((result or {}).get("image_url") or "").strip()
            if image_url:
                image_attachment = (result or {}).get("attachment")
                attachments = []
                if isinstance(image_attachment, dict):
                    attachments.append(
                        {
                            "id": image_attachment.get("id") or "",
                            "name": image_attachment.get("name") or "生成图片",
                            "category": image_attachment.get("category") or "image",
                        }
                    )
                attachments.append({"category": "generated_image", "name": "生成图片", "url": image_url})
            message_service.complete_assistant_message(
                db,
                message_id=int(message_id),
                content=final_text,
                attachments=attachments,
            )
            if conversation_id:
                conversation = db.get(Conversation, int(conversation_id))
                if conversation:
                    conversation_service.touch_conversation(
                        db,
                        conversation,
                        model=str(task_data.get("model") or ""),
                        last_message_at=datetime.now(),
                    )
    except Exception:
        logger.warning(
            "[task-worker] task message finalize failed task_id=%s message_id=%s",
            task_data.get("id"),
            message_id,
            exc_info=True,
        )


def run_image_task(task_data: dict) -> dict:
    logger.info("[route-enter] run_image_task task_id=%s", task_data.get("id"))
    att = task_data.get("attachment_ids") or []
    logger.info(
        "[image-task-route] task_id=%s has_attachments=%s route=dispatch_image_request",
        task_data.get("id"),
        bool(att),
    )
    rid_t, att_t, im_t = set_ai_request_context(att, None)
    try:
        return _run_image_task_impl(task_data)
    finally:
        reset_ai_request_context(rid_t, att_t, im_t)


def _run_image_task_impl(task_data: dict) -> dict:
    logger.info("[route-enter] _run_image_task_impl task_id=%s", task_data.get("id"))
    attachment_ids = task_data.get("attachment_ids") or []
    user_prompt = (task_data.get("prompt") or "").strip()
    ref_preview = image_service.build_image_reference_data_urls(attachment_ids)
    ref_count = len(ref_preview)
    model_s = str(task_data.get("model") or "")
    route_meta = image_route_meta(model_s)
    logger.info(
        "[image-task-enter] task_id=%s model=%s adapter=%s capability=%s "
        "has_attachments=%s reference_images_count=%s image_intent=%s reference_source=%s intent_confidence=%s",
        task_data.get("id"),
        task_data.get("model"),
        route_meta.get("adapter"),
        route_meta.get("capability"),
        bool(attachment_ids),
        ref_count,
        task_data.get("image_intent") or "",
        task_data.get("reference_source") or "",
        task_data.get("image_intent_confidence") or 0,
    )
    logger.info(
        "[image-dispatch] task_id=%s model=%s adapter=%s supports_image_to_image=%s "
        "reference_images_count=%s",
        task_data.get("id"),
        task_data.get("model"),
        route_meta.get("adapter"),
        route_meta.get("supports_image_to_image"),
        ref_count,
    )

    generation_prompt = _image_generation_prompt(task_data)
    data = image_service.dispatch_image_request(
        str(task_data.get("model") or ""),
        generation_prompt,
        attachment_ids,
        str(task_data.get("size") or "1024x1024"),
        int(task_data.get("n") or 1),
        reference_images=ref_preview,
    )
    image_result = image_service.extract_image_result(data)
    if not image_result:
        raise RuntimeError(f"上游 HTTP 200 但未解析到图片字段。返回: {str(data)[:4000]}")
    image_result, image_attachment = _persist_generated_image(image_result, str(task_data.get("id") or ""))
    return {
        "text": "已生成图片。",
        "image_url": image_result,
        "attachment": image_attachment,
        "note": "任务已完成。",
    }


def run_video_task(task_data: dict) -> dict:
    raise RuntimeError(
        "视频模式入口已保留，但真实视频生成接口还没有正式接通。"
        " 当前版本先不要把它当成可用生产能力。"
    )


def _parse_one_task_file(path: Path) -> Optional[dict]:
    """从磁盘读取一条任务；非法文件返回 None。成功时保证 task_data['id'] 与文件名 stem 一致。"""
    if path.suffix.lower() != ".json":
        return None
    file_id = path.stem
    if not file_id:
        logger.warning("[task] parse skip empty stem path=%s", path)
        return None
    try:
        task_data = safe_json_load(path)
    except Exception as e:
        logger.warning("[task] parse skip corrupt json path=%s err=%s", path, repr(e))
        return None

    if not isinstance(task_data, dict):
        logger.warning("[task] parse skip non-dict path=%s", path)
        return None

    inner_id = task_data.get("id")
    if inner_id != file_id:
        logger.warning(
            "[task] parse id mismatch file_stem=%r json_id=%r path=%s (use stem)",
            file_id,
            inner_id,
            path,
        )
        task_data["id"] = file_id
    return task_data


def list_queued_tasks_fifo() -> list[dict]:
    """所有 status=queued 且可执行的任务，按 created_at 升序（再按 mtime）排队，避免被历史 queued 永远挡在后面。"""
    with get_session_factory()() as db:
        rows = (
            db.query(GenerationTask)
            .filter(GenerationTask.status == "queued")
            .order_by(GenerationTask.created_at.asc())
            .limit(200)
            .all()
        )
        if rows:
            return [_task_row_to_dict(row) for row in rows if row.mode]

    rows: list[tuple[str, float, dict]] = []
    for path in list_task_files():
        task_data = _parse_one_task_file(path)
        if not task_data:
            continue
        if task_data.get("status") != "queued":
            continue
        if not task_data.get("mode"):
            logger.warning(
                "[task] fifo skip missing mode path=%s id=%s",
                path,
                task_data.get("id"),
            )
            continue
        created = str(task_data.get("created_at") or "")
        try:
            mkey = path.stat().st_mtime
        except OSError:
            mkey = 0.0
        rows.append((created, mkey, task_data))

    rows.sort(key=lambda x: (x[0], x[1]))
    return [r[2] for r in rows]


def claim_next_queued_task() -> Optional[dict]:
    with _task_claim_lock:
        with get_session_factory()() as db:
            row = (
                db.query(GenerationTask)
                .filter(GenerationTask.status == "queued")
                .order_by(GenerationTask.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if row:
                row.status = "running"
                row.progress_text = "任务处理中，请稍候。"
                row.started_at = datetime.now()
                row.updated_at = datetime.now()
                row.error_message = ""
                db.add(row)
                db.commit()
                db.refresh(row)
                task_data = _task_row_to_dict(row)
                _sync_task_oss_snapshot(task_data)
                return task_data

        for next_task in list_queued_tasks_fifo():
            task_id = str(next_task.get("id") or "")
            if task_id and not _load_task_db(task_id):
                _save_task_db(next_task)
                claimed = update_task(
                    task_id,
                    status="running",
                    progress_text="任务处理中，请稍候。",
                    started_at=now_iso(),
                    error_message="",
                )
                if claimed:
                    return claimed
    return None


def list_recent_tasks(limit: int = 20) -> list[dict]:
    lim = max(1, min(int(limit or 20), 100))
    with get_session_factory()() as db:
        rows = (
            db.query(GenerationTask)
            .order_by(GenerationTask.created_at.desc())
            .limit(lim)
            .all()
        )
        if rows:
            return [_task_row_to_dict(row) for row in rows]

    tasks = []
    for path in reversed(list_task_files()):
        try:
            task_data = safe_json_load(path)
        except Exception:
            continue
        tasks.append(task_data)
        if len(tasks) >= lim:
            break
    return tasks


def normalize_unfinished_tasks() -> None:
    cutoff = datetime.now().timestamp() - TASK_RUNNING_REQUEUE_SECONDS
    with _task_claim_lock:
        with get_session_factory()() as db:
            rows = (
                db.query(GenerationTask)
                .filter(GenerationTask.status == "running")
                .limit(1000)
                .all()
            )
            for row in rows:
                heartbeat = row.updated_at or row.started_at or row.created_at
                if heartbeat and heartbeat.timestamp() > cutoff:
                    continue
                row.status = "queued"
                row.progress_text = "服务重启后已重新入队。"
                row.started_at = None
                row.updated_at = datetime.now()
                row.error_message = ""
                db.add(row)
                logger.info("[task] normalize db running->queued task_id=%s", row.id)
            if rows:
                db.commit()

    for path in list_task_files():
        if path.suffix.lower() != ".json":
            continue
        file_id = path.stem
        try:
            with task_lock:
                try:
                    task_data = safe_json_load(path)
                except Exception as e:
                    logger.warning(
                        "[task] normalize skip unreadable path=%s err=%s",
                        path,
                        repr(e),
                    )
                    continue
                if not isinstance(task_data, dict):
                    continue
                inner_id = task_data.get("id")
                if inner_id != file_id:
                    logger.warning(
                        "[task] normalize id mismatch file_stem=%r json_id=%r path=%s",
                        file_id,
                        inner_id,
                        path,
                    )
                    task_data["id"] = file_id
                if task_data.get("status") == "running":
                    task_data["status"] = "queued"
                    task_data["progress_text"] = "服务重启后已重新入队。"
                    task_data["updated_at"] = now_iso()
                    task_data["started_at"] = None
                    safe_json_dump(path, task_data)
                try:
                    _save_task_db(task_data)
                except Exception:
                    logger.warning(
                        "[task] normalize import legacy task failed path=%s id=%s",
                        path,
                        task_data.get("id"),
                        exc_info=True,
                    )
        except Exception as e:
            logger.warning("[task] normalize failed path=%s err=%s", path, repr(e))


def task_worker_loop() -> None:
    from app.config import TASK_POLL_INTERVAL_SECONDS

    global _worker_tasks_dir_logged
    if not _worker_tasks_dir_logged:
        d = _tasks_dir_resolved()
        logger.info("[task-worker] TASKS_DIR=%s", d)
        _worker_tasks_dir_logged = True

    logger.info("[task-worker] huairen-task-worker thread entered task_worker_loop")
    logger.info("[task-worker] worker started (daemon thread running task_worker_loop)")

    try:
        normalize_unfinished_tasks()
    except BaseException:
        logger.critical(
            "[task-worker] normalize_unfinished_tasks crashed (worker continues):\n%s",
            traceback.format_exc(),
        )

    while True:
        try:
            latest_task = claim_next_queued_task()
            if not latest_task:
                time.sleep(TASK_POLL_INTERVAL_SECONDS)
                continue

            task_id = str(latest_task.get("id") or "")
            task_mode = latest_task.get("mode")
            try:
                if task_mode == "image":
                    result = run_image_task(latest_task)
                elif task_mode == "artifact":
                    result = artifact_generation_service.run_artifact_task(latest_task)
                elif task_mode == "video":
                    result = run_video_task(latest_task)
                else:
                    raise RuntimeError(f"暂不支持这种任务模式：{task_mode}")

                after_run = load_task(task_id) or {}
                after_status = str(after_run.get("status") or "")
                if after_status in {"cancelled", "failed"}:
                    logger.info(
                        "[task-worker] task finished after terminal state task_id=%s status=%s",
                        task_id,
                        after_status,
                    )
                    continue

                if update_task(
                    task_id,
                    status="succeeded",
                    progress_text="任务已完成。",
                    finished_at=now_iso(),
                    result=result,
                    error_message="",
                ) is None:
                    logger.warning(
                        "[task-worker] succeeded but could not persist task_id=%s",
                        task_id,
                    )
                _finalize_task_message(latest_task, result=result)
            except Exception as e:
                tb_text = traceback.format_exc()
                logger.error("[task-worker] task failed task_id=%s\n%s", task_id, tb_text)
                err_msg = _error_message_with_tb(e, tb_text)
                if update_task(
                    task_id,
                    status="failed",
                    progress_text="任务失败。",
                    finished_at=now_iso(),
                    error_message=err_msg,
                    result={},
                ) is None:
                    logger.warning(
                        "[task-worker] failed state could not persist task_id=%s err=%s",
                        task_id,
                        repr(e),
                    )
                _finalize_task_message(latest_task, error_message=err_msg)
        except BaseException:
            logger.error(
                "[task-worker] outer loop error (worker continues after sleep):\n%s",
                traceback.format_exc(),
            )
            time.sleep(TASK_POLL_INTERVAL_SECONDS)


def log_image_worker_runtime_probe() -> None:
    """启动时运行时探测：sys.modules、find_spec、关键函数源文件（不主动 import rembg 以免触发副作用）。"""
    import sys

    logger.info("[runtime-probe] ===== image worker / rembg trace probe start =====")
    for m in ("rembg", "pooch"):
        logger.info("[runtime-sys.modules] %s in sys.modules=%s", m, m in sys.modules)
    u2_keys = [k for k in sys.modules if "u2net" in k.lower()]
    logger.info("[runtime-sys.modules] keys containing u2net (count=%d) sample=%r", len(u2_keys), u2_keys[:25])
    for mod in ("rembg", "pooch"):
        try:
            spec = importlib.util.find_spec(mod)
        except Exception as ex:
            logger.info("[runtime-find_spec] %s error=%r", mod, ex)
        else:
            logger.info(
                "[runtime-find_spec] %s spec_found=%s origin=%r",
                mod,
                spec is not None,
                getattr(spec, "origin", None),
            )
    if "rembg" in sys.modules:
        rb = sys.modules["rembg"]
        logger.info(
            "[runtime-rembg-loaded] __file__=%r remove=%r new_session=%r",
            getattr(rb, "__file__", None),
            getattr(rb, "remove", None),
            getattr(rb, "new_session", None),
        )
        for sym in ("remove", "new_session"):
            logger.info("[runtime-rembg-symbols] rembg.%s=%r", sym, getattr(rb, sym, None))
    else:
        logger.info("[runtime-rembg-loaded] rembg not in sys.modules at startup (no eager import done)")
        for sym in ("remove", "new_session"):
            logger.info("[runtime-rembg-symbols] rembg.%s skipped (rembg not loaded)", sym)
    try:
        logger.info("[route-source] run_image_task -> %s", inspect.getsourcefile(run_image_task))
    except Exception as ex:
        logger.warning("[route-source] run_image_task inspect failed: %s", ex)
    try:
        logger.info("[route-source] dispatch_ai_request -> %s", inspect.getsourcefile(image_service.dispatch_ai_request))
        logger.info(
            "[route-source] call_openai_image_generation_api -> %s",
            inspect.getsourcefile(image_service.call_openai_image_generation_api),
        )
        logger.info(
            "[route-source] call_openai_image_edits_api -> %s",
            inspect.getsourcefile(image_service.call_openai_image_edits_api),
        )
    except Exception as ex:
        logger.warning("[route-source] image_service inspect failed: %s", ex)
    logger.info("[runtime-probe] ===== image worker / rembg trace probe end =====")


def _task_worker_thread_main() -> None:
    """线程入口：若 task_worker_loop 意外退出，打完整 traceback（正常为无限循环不应返回）。"""
    try:
        task_worker_loop()
    except BaseException:
        logger.critical(
            "[task-worker] task_worker_loop thread terminated unexpectedly:\n%s",
            traceback.format_exc(),
        )
        raise


def ensure_task_worker_started() -> None:
    from app.config import TASK_WORKER_CONCURRENCY

    global task_worker_started

    if task_worker_started:
        return

    logger.info(
        "[task-worker] starting daemon threads count=%s TASKS_DIR=%s",
        TASK_WORKER_CONCURRENCY,
        _tasks_dir_resolved(),
    )
    log_image_worker_runtime_probe()
    workers = []
    for i in range(TASK_WORKER_CONCURRENCY):
        worker = threading.Thread(
            target=_task_worker_thread_main,
            name=f"huairen-task-worker-{i + 1}",
            daemon=True,
        )
        worker.start()
        workers.append(worker)
    task_worker_started = True
    logger.info(
        "[task-worker] worker thread start() returned alive_count=%s",
        sum(1 for worker in workers if worker.is_alive()),
    )
