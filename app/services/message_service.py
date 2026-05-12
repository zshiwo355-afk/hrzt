"""数据库消息服务。"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Optional, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database_models import Message
from app.services.attachment_service import save_attachment_meta_db, read_attachment_meta_any

_DATA_URL_RE = re.compile(
    r"data:[^,\s;]{1,80}(?:;[^,\s]{1,80})*;base64,[A-Za-z0-9+/=\r\n]+",
    re.IGNORECASE,
)
_MAX_HISTORY_CONTENT_CHARS = 60_000
_MAX_ATTACHMENT_URL_CHARS = 2_000


def build_attachment_snapshots(attachment_ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for attachment_id in attachment_ids or []:
        meta = read_attachment_meta_any(attachment_id)
        if not meta:
            rows.append({"id": attachment_id, "name": "", "category": "document"})
            continue
        rows.append(
            {
                "id": attachment_id,
                "name": meta.get("original_name") or "",
                "category": meta.get("category") or "document",
            }
        )
    return rows


def create_user_message(
    db: Session,
    *,
    conversation_id: int,
    user_id: int,
    content: str,
    model: Optional[str],
    attachments: Optional[list[dict]],
) -> Message:
    msg = Message(
        conversation_id=int(conversation_id),
        user_id=int(user_id),
        role="user",
        status="completed",
        model=(model or "").strip() or None,
        content=content or "",
        attachments_json=attachments or [],
        completed_at=datetime.now(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    for item in attachments or []:
        attachment_id = str((item or {}).get("id") or "")
        if not attachment_id:
            continue
        meta = read_attachment_meta_any(attachment_id)
        if meta:
            save_attachment_meta_db(
                meta,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=msg.id,
                source="message_attachment",
            )
    return msg


def create_assistant_placeholder(
    db: Session,
    *,
    conversation_id: int,
    user_id: int,
    model: Optional[str],
) -> Message:
    msg = Message(
        conversation_id=int(conversation_id),
        user_id=int(user_id),
        role="assistant",
        status="streaming",
        model=(model or "").strip() or None,
        content="",
        attachments_json=[],
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def complete_assistant_message(
    db: Session,
    *,
    message_id: int,
    content: str,
    attachments: Optional[list[dict]] = None,
) -> Optional[Message]:
    msg = db.get(Message, int(message_id))
    if not msg:
        return None
    msg.status = "completed"
    msg.content = content or ""
    if attachments is not None:
        msg.attachments_json = attachments
    msg.error_message = None
    msg.completed_at = datetime.now()
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def sanitize_history_content(content: str) -> str:
    text = content or ""
    if "base64," in text.lower() or "data:" in text.lower():
        text = _DATA_URL_RE.sub("[已省略内嵌文件数据]", text)
    if len(text) > _MAX_HISTORY_CONTENT_CHARS:
        return text[:_MAX_HISTORY_CONTENT_CHARS] + "\n\n[历史消息内容过长，已截断预览]"
    return text


def sanitize_history_attachments(attachments: Optional[Union[list[dict], dict]]) -> list[dict]:
    if not isinstance(attachments, list):
        return []
    rows: list[dict] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        row = {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "category": str(item.get("category") or "document"),
        }
        url = str(item.get("url") or "").strip()
        if url and not url.lower().startswith("data:") and len(url) <= _MAX_ATTACHMENT_URL_CHARS:
            row["url"] = url
        rows.append(row)
    return rows


def extract_generated_image_url(attachments: Optional[Union[list[dict], dict]]) -> str:
    first_image_attachment_id = ""
    if isinstance(attachments, list):
        for item in attachments:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            if category == "image" and item.get("id") and not first_image_attachment_id:
                first_image_attachment_id = str(item.get("id") or "")
            if category == "generated_image" and item.get("url"):
                url = str(item.get("url") or "").strip()
                if url and not url.lower().startswith("data:") and len(url) <= _MAX_ATTACHMENT_URL_CHARS:
                    return url
    if first_image_attachment_id:
        return f"/api/attachments/{first_image_attachment_id}"
    return ""


def fail_assistant_message(db: Session, *, message_id: int, error_message: str) -> Optional[Message]:
    msg = db.get(Message, int(message_id))
    if not msg:
        return None
    if msg.status == "completed":
        return msg
    msg.status = "failed"
    msg.error_message = error_message or ""
    msg.completed_at = datetime.now()
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def list_messages_for_conversation(
    db: Session,
    conversation_id: int,
    *,
    limit: int = 50,
    before_id: Optional[int] = None,
) -> list[Message]:
    lim = max(1, min(int(limit or 50), 200))
    stmt = (
        select(Message)
        .where(Message.conversation_id == int(conversation_id))
        .order_by(Message.id.desc())
        .limit(lim)
    )
    if before_id:
        stmt = stmt.where(Message.id < int(before_id))
    return list(reversed(list(db.scalars(stmt).all())))
