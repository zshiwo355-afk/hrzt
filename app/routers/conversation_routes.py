"""数据库会话与消息接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.models import ConversationCreateRequest, ConversationUpdateRequest
from app.services import conversation_service, message_service, model_service, task_service

router = APIRouter(tags=["conversations"])


@router.post("/api/conversations")
def create_conversation(
    req: ConversationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    if (req.model or "").strip():
        model_service.ensure_model_allowed(req.model, mode=req.mode)
    conversation = conversation_service.create_conversation(
        db,
        user_id=user_id,
        mode=req.mode,
        title=req.title,
        model=req.model,
    )
    return {
        "conversation": {
            "id": conversation.id,
            "title": conversation.title,
            "mode": conversation.mode,
            "model": conversation.model or "",
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        }
    }


@router.get("/api/conversations")
def list_conversations(
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    rows = conversation_service.list_conversations_for_user(db, user_id, limit=limit, offset=offset)
    return {
        "conversations": [
            {
                "id": item["conversation"].id,
                "title": item["conversation"].title,
                "mode": item["conversation"].mode,
                "model": item["conversation"].model or "",
                "created_at": item["conversation"].created_at.isoformat(),
                "updated_at": item["conversation"].updated_at.isoformat(),
                "last_message_at": (
                    item["conversation"].last_message_at.isoformat()
                    if item["conversation"].last_message_at
                    else None
                ),
                "message_count": item["message_count"],
            }
            for item in rows
        ]
    }


@router.get("/api/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    before_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    conversation = conversation_service.get_conversation_for_user(db, conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或无权限。")

    messages = message_service.list_messages_for_conversation(
        db,
        conversation.id,
        limit=limit,
        before_id=before_id,
    )
    return {
        "conversation": {
            "id": conversation.id,
            "title": conversation.title,
            "mode": conversation.mode,
            "model": conversation.model or "",
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        },
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "status": msg.status,
                "content": message_service.sanitize_history_content(msg.content or ""),
                "model": msg.model or "",
                "attachments": message_service.sanitize_history_attachments(msg.attachments_json),
                "image_url": message_service.extract_generated_image_url(msg.attachments_json),
                "task_id": (
                    task_service.find_active_task_id_for_message(msg.id)
                    if msg.status == "streaming"
                    else ""
                ),
                "error_message": msg.error_message or "",
                "created_at": msg.created_at.isoformat(),
                "completed_at": msg.completed_at.isoformat() if msg.completed_at else None,
            }
            for msg in messages
        ],
    }


@router.put("/api/conversations/{conversation_id}")
def update_conversation(
    conversation_id: int,
    req: ConversationUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    conversation = conversation_service.get_conversation_for_user(db, conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或无权限。")
    try:
        conversation = conversation_service.rename_conversation(db, conversation, req.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "conversation": {
            "id": conversation.id,
            "title": conversation.title,
            "mode": conversation.mode,
            "model": conversation.model or "",
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        }
    }


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)
    conversation = conversation_service.get_conversation_for_user(db, conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或无权限。")
    conversation_service.delete_conversation(db, conversation)
    return {"ok": True}
