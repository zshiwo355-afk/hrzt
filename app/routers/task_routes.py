"""异步任务。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import require_auth, resolve_history_user_id
from app.db import get_db
from app.logging_config import logger
from app.models import OutputIntentRequest, TaskCreateRequest
from app.services import (
    auth_service,
    conversation_service,
    image_service,
    message_service,
    model_service,
    output_intent_service,
    task_service,
)

router = APIRouter(tags=["tasks"])


@router.post("/api/output-intent")
def detect_output_intent(req: OutputIntentRequest, request: Request):
    require_auth(request)
    return output_intent_service.detect_output_intent(req.prompt, req.mode)


@router.post("/api/tasks")
def create_task(req: TaskCreateRequest, request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)

    if req.mode == "video":
        raise HTTPException(status_code=400, detail="video disabled")

    if not (req.prompt or "").strip() and not (req.attachment_ids or []):
        raise HTTPException(status_code=400, detail="请至少输入提示词，或上传附件。")

    task_kwargs = {
        "history_user_id": resolve_history_user_id(request),
    }

    if req.mode == "image":
        model_service.ensure_model_allowed(req.model, mode="image")
        if req.conversation_id:
            user = auth_service.get_user_by_id(db, user_id)
            if not user or not user.is_active:
                raise HTTPException(status_code=401, detail="请先登录。")
            conversation = conversation_service.get_conversation_for_user(db, req.conversation_id, user_id)
            if not conversation:
                raise HTTPException(status_code=404, detail="会话不存在或无权限。")

            attachments = message_service.build_attachment_snapshots(req.attachment_ids or [])
            message_service.create_user_message(
                db,
                conversation_id=conversation.id,
                user_id=user.id,
                content=(req.prompt or "").strip(),
                model=req.model,
                attachments=attachments,
            )
            assistant_message = message_service.create_assistant_placeholder(
                db,
                conversation_id=conversation.id,
                user_id=user.id,
                model=req.model,
            )
            conversation_service.maybe_set_first_title(db, conversation, (req.prompt or "").strip())
            conversation_service.touch_conversation(
                db,
                conversation,
                model=req.model,
                last_message_at=datetime.now(),
            )
            task_kwargs.update(
                {
                    "conversation_id": conversation.id,
                    "assistant_message_id": assistant_message.id,
                }
            )
    elif req.mode == "artifact":
        if (req.artifact_type or "").strip().lower() not in {"docx", "xlsx", "pptx", "pdf", "txt", "md", "csv"}:
            raise HTTPException(status_code=400, detail="当前文件任务只支持 docx、xlsx、pptx、pdf、txt、md 或 csv。")
        intent = output_intent_service.detect_output_intent(req.prompt, "text")
        if not intent.get("should_use_task"):
            raise HTTPException(status_code=400, detail="这是能力询问或普通对话，不应创建文件任务。")
        model_service.ensure_model_allowed(req.model, mode="text")
        if not req.conversation_id:
            raise HTTPException(status_code=400, detail="文件任务缺少 conversation_id。")
        user = auth_service.get_user_by_id(db, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="请先登录。")
        conversation = conversation_service.get_conversation_for_user(db, req.conversation_id, user_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="会话不存在或无权限。")

        attachments = message_service.build_attachment_snapshots(req.attachment_ids or [])
        message_service.create_user_message(
            db,
            conversation_id=conversation.id,
            user_id=user.id,
            content=(req.prompt or "").strip(),
            model=req.model,
            attachments=attachments,
        )
        assistant_message = message_service.create_assistant_placeholder(
            db,
            conversation_id=conversation.id,
            user_id=user.id,
            model=req.model,
        )
        conversation_service.maybe_set_first_title(db, conversation, (req.prompt or "").strip())
        conversation_service.touch_conversation(
            db,
            conversation,
            model=req.model,
            last_message_at=datetime.now(),
        )
        task_kwargs.update(
            {
                "artifact_type": (req.artifact_type or "").strip().lower(),
                "conversation_id": conversation.id,
                "assistant_message_id": assistant_message.id,
            }
        )
    else:
        raise HTTPException(status_code=400, detail="当前任务制只支持图片和文件生成。")

    task_data = task_service.create_generation_task(
        req,
        **task_kwargs,
    )
    logger.info(
        "[task-created] task_id=%s mode=%s model=%s attachment_count=%s reference_images_count=%s artifact_type=%s",
        task_data.get("id"),
        req.mode,
        req.model,
        len(req.attachment_ids or []),
        len(image_service.build_image_reference_data_urls(req.attachment_ids or [])),
        task_data.get("artifact_type") or "",
    )
    return {"task": task_service.build_task_public(task_data)}


@router.get("/api/tasks/{task_id}")
def get_task(task_id: str, request: Request):
    require_auth(request)

    task_data = task_service.load_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="任务不存在或已失效。")

    return {"task": task_service.build_task_public(task_data)}


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request):
    require_auth(request)

    task_data = task_service.cancel_task(task_id)
    if not task_data:
        raise HTTPException(status_code=404, detail="任务不存在或已失效。")

    return {"task": task_service.build_task_public(task_data)}


@router.get("/api/tasks")
def list_tasks(request: Request, limit: int = 20):
    require_auth(request)

    tasks = [task_service.build_task_public(row) for row in task_service.list_recent_tasks(limit)]
    return {"tasks": tasks}
