"""聊天记录 API（OSS）。"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request

from app.auth import require_auth, resolve_history_user_id
from app.config import oss_configured
from app.logging_config import logger
from app.services import history_service

router = APIRouter(prefix="/api/history", tags=["history"])


def _require_oss() -> None:
    if not oss_configured():
        raise HTTPException(
            status_code=503,
            detail="OSS 未配置（需 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_ENDPOINT / OSS_BUCKET）。",
        )


@router.get("/conversations")
def list_conversations(
    request: Request,
    mode: Optional[str] = Query(None, description="text | image | video，不传则返回全部"),
):
    require_auth(request)
    _require_oss()
    uid = resolve_history_user_id(request)
    rows = history_service.list_conversation_index(uid, mode=mode)
    return {"conversations": rows, "history_user_id": uid}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    require_auth(request)
    _require_oss()
    uid = resolve_history_user_id(request)
    doc = history_service.load_conversation_doc(uid, conversation_id)
    if not doc:
        raise HTTPException(status_code=404, detail="会话不存在。")
    return {"conversation": doc}


@router.post("/conversations")
def post_create_conversation(
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    require_auth(request)
    _require_oss()
    uid = resolve_history_user_id(request)
    mode = str(body.get("mode") or "text")
    if mode not in ("text", "image", "video"):
        raise HTTPException(status_code=400, detail="mode 必须是 text、image 或 video。")
    title = str(body.get("title") or "新建聊天")
    model = str(body.get("model") or "")
    try:
        doc = history_service.create_conversation(uid, mode=mode, title=title, model=model)
    except Exception as e:
        logger.warning("[history] create failed uid=%s err=%s", uid, repr(e))
        raise HTTPException(status_code=500, detail="创建会话失败。") from e
    return {"conversation": doc}


@router.put("/conversations/{conversation_id}")
def put_conversation(
    conversation_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
):
    require_auth(request)
    _require_oss()
    uid = resolve_history_user_id(request)
    body = dict(body)
    body["id"] = conversation_id
    try:
        doc = history_service.save_conversation_doc(uid, body)
    except Exception as e:
        logger.warning("[history] put failed uid=%s id=%s err=%s", uid, conversation_id, repr(e))
        raise HTTPException(status_code=500, detail="保存会话失败。") from e
    return {"conversation": doc}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request):
    require_auth(request)
    _require_oss()
    uid = resolve_history_user_id(request)
    history_service.delete_conversation(uid, conversation_id)
    return {"ok": True}


@router.post("/conversations/{conversation_id}/messages")
def post_append_messages(
    conversation_id: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
):
    require_auth(request)
    _require_oss()
    uid = resolve_history_user_id(request)
    msgs = body.get("messages")
    if msgs is None and isinstance(body.get("message"), dict):
        msgs = [body["message"]]
    if not isinstance(msgs, list):
        raise HTTPException(status_code=400, detail="请提供 messages 数组或单条 message 对象。")
    try:
        doc = history_service.append_messages(uid, conversation_id, msgs)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在。") from None
    except Exception as e:
        logger.warning("[history] append failed uid=%s id=%s err=%s", uid, conversation_id, repr(e))
        raise HTTPException(status_code=500, detail="追加消息失败。") from e
    return {"conversation": doc}
