"""数据库会话服务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database_models import Conversation, Message


def create_conversation(
    db: Session,
    *,
    user_id: int,
    mode: str = "text",
    title: str = "新建聊天",
    model: str = "",
) -> Conversation:
    conversation = Conversation(
        user_id=int(user_id),
        mode=mode if mode in {"text", "image", "video"} else "text",
        title=(title or "新建聊天").strip() or "新建聊天",
        model=(model or "").strip() or None,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation_for_user(db: Session, conversation_id: int, user_id: int) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.id == int(conversation_id),
        Conversation.user_id == int(user_id),
    )
    return db.scalar(stmt)


def list_conversations_for_user(db: Session, user_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
    lim = max(1, min(int(limit or 100), 200))
    off = max(0, int(offset or 0))
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == int(user_id))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .offset(off)
        .limit(lim)
    )
    conversations = list(db.scalars(stmt).all())
    conversation_ids = [conversation.id for conversation in conversations]
    counts: dict[int, int] = {}
    if conversation_ids:
        count_stmt = (
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_(conversation_ids))
            .group_by(Message.conversation_id)
        )
        counts = {
            int(conversation_id): int(message_count or 0)
            for conversation_id, message_count in db.execute(count_stmt).all()
        }

    result: list[dict] = []
    for conversation in conversations:
        result.append({
            "conversation": conversation,
            "message_count": counts.get(int(conversation.id), 0),
        })
    return result


def touch_conversation(
    db: Session,
    conversation: Conversation,
    *,
    title: str | None = None,
    model: str | None = None,
    last_message_at: datetime | None = None,
) -> Conversation:
    if title is not None:
        cleaned = title.strip()
        if cleaned:
            conversation.title = cleaned
    if model is not None:
        conversation.model = model.strip() or None
    if last_message_at is not None:
        conversation.last_message_at = last_message_at
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def maybe_set_first_title(db: Session, conversation: Conversation, first_user_text: str) -> Conversation:
    if (conversation.title or "").strip() and conversation.title != "新建聊天":
        return conversation
    title = (first_user_text or "").strip()[:20]
    if not title:
        return conversation
    return touch_conversation(db, conversation, title=title)


def rename_conversation(db: Session, conversation: Conversation, title: str) -> Conversation:
    cleaned = (title or "").strip()
    if not cleaned:
        raise ValueError("标题不能为空")
    return touch_conversation(db, conversation, title=cleaned)


def delete_conversation(db: Session, conversation: Conversation) -> None:
    db.delete(conversation)
    db.commit()
