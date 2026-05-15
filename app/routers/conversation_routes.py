"""数据库会话与消息接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.db import get_db
from app.models import (
    ConversationCreateRequest,
    ConversationProjectRequest,
    ConversationUpdateRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
)
from app.services import conversation_service, message_service, model_service, task_service

router = APIRouter(tags=["conversations"])


def _project_row(project, conversation_count: int | None = None):
    row = {
        "id": project.id,
        "name": project.name,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }
    if conversation_count is not None:
        row["conversation_count"] = conversation_count
    return row


def _message_row(msg):
    image_ref = message_service.extract_generated_image_ref(msg.attachments_json)
    return {
        "id": msg.id,
        "role": msg.role,
        "status": msg.status,
        "content": message_service.sanitize_history_content(msg.content or ""),
        "model": msg.model or "",
        "attachments": message_service.sanitize_history_attachments(msg.attachments_json),
        "image_url": image_ref.get("url") or "",
        "image_thumb_url": image_ref.get("thumb_url") or "",
        "task_id": (
            task_service.find_active_task_id_for_message(msg.id)
            if msg.status == "streaming"
            else ""
        ),
        "error_message": msg.error_message or "",
        "created_at": msg.created_at.isoformat(),
        "completed_at": msg.completed_at.isoformat() if msg.completed_at else None,
    }


def _conversation_row(conversation, message_count: int | None = None):
    row = {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "title": conversation.title,
        "mode": conversation.mode,
        "model": conversation.model or "",
        "summary": conversation.summary or "",
        "has_summary": bool((conversation.summary or "").strip()),
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
    }
    if message_count is not None:
        row["message_count"] = message_count
    return row


@router.get("/api/projects")
def list_projects(request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)
    rows = conversation_service.list_projects_for_user(db, user_id)
    return {
        "projects": [
            _project_row(item["project"], item["conversation_count"])
            for item in rows
        ]
    }


@router.post("/api/projects")
def create_project(req: ProjectCreateRequest, request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)
    project = conversation_service.create_project(db, user_id=user_id, name=req.name)
    return {"project": _project_row(project, 0)}


@router.put("/api/projects/{project_id}")
def update_project(
    project_id: int,
    req: ProjectUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    project = conversation_service.get_project_for_user(db, project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权限。")
    try:
        project = conversation_service.rename_project(db, project, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    detail = conversation_service.get_project_detail_for_user(db, project_id, user_id)
    return {
        "project": _project_row(project, detail["conversation_count"] if detail else 0)
    }


@router.get("/api/projects/{project_id}")
def get_project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)
    detail = conversation_service.get_project_detail_for_user(db, project_id, user_id)
    if not detail:
        raise HTTPException(status_code=404, detail="项目不存在或无权限。")
    return {
        "project": _project_row(detail["project"], detail["conversation_count"]),
        "conversations": [
            _conversation_row(
                conversation,
                detail["message_counts"].get(int(conversation.id), 0),
            )
            for conversation in detail["conversations"]
        ],
        "conversation_count": detail["conversation_count"],
        "updated_at": detail["project"].updated_at.isoformat(),
    }


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)
    project = conversation_service.get_project_for_user(db, project_id, user_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权限。")
    conversation_service.delete_project(db, project)
    return {"ok": True}


@router.post("/api/conversations")
def create_conversation(
    req: ConversationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    if (req.model or "").strip():
        model_service.ensure_model_allowed(req.model, mode=req.mode)
    if req.project_id and not conversation_service.get_project_for_user(db, req.project_id, user_id):
        raise HTTPException(status_code=404, detail="项目不存在或无权限。")
    conversation = conversation_service.create_conversation(
        db,
        user_id=user_id,
        mode=req.mode,
        title=req.title,
        model=req.model,
        project_id=req.project_id,
    )
    return {
        "conversation": _conversation_row(conversation)
    }


@router.put("/api/conversations/{conversation_id}/project")
def move_conversation_project(
    conversation_id: int,
    req: ConversationProjectRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = require_auth(request)
    conversation = conversation_service.get_conversation_for_user(db, conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或无权限。")
    project = None
    if req.project_id:
        project = conversation_service.get_project_for_user(db, req.project_id, user_id)
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在或无权限。")
    conversation = conversation_service.move_conversation_to_project(db, conversation, project)
    return {"conversation": _conversation_row(conversation)}


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
                **_conversation_row(item["conversation"], item["message_count"]),
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
        "conversation": _conversation_row(conversation),
        "messages": [_message_row(msg) for msg in messages],
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
        "conversation": _conversation_row(conversation)
    }


@router.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = require_auth(request)
    conversation = conversation_service.get_conversation_for_user(db, conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或无权限。")
    conversation_service.delete_conversation(db, conversation)
    return {"ok": True}
