"""数据库会话服务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database_models import Conversation, Message, Project


def create_project(db: Session, *, user_id: int, name: str = "新项目") -> Project:
    project = Project(
        user_id=int(user_id),
        name=(name or "新项目").strip() or "新项目",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects_for_user(db: Session, user_id: int) -> list[dict]:
    stmt = (
        select(Project)
        .where(Project.user_id == int(user_id))
        .order_by(Project.updated_at.desc(), Project.id.desc())
    )
    projects = list(db.scalars(stmt).all())
    project_ids = [project.id for project in projects]
    counts: dict[int, int] = {}
    if project_ids:
        count_stmt = (
            select(Conversation.project_id, func.count(Conversation.id))
            .where(Conversation.user_id == int(user_id))
            .where(Conversation.project_id.in_(project_ids))
            .group_by(Conversation.project_id)
        )
        counts = {
            int(project_id): int(conversation_count or 0)
            for project_id, conversation_count in db.execute(count_stmt).all()
            if project_id is not None
        }
    return [{"project": project, "conversation_count": counts.get(int(project.id), 0)} for project in projects]


def get_project_for_user(db: Session, project_id: int, user_id: int) -> Project | None:
    stmt = select(Project).where(Project.id == int(project_id), Project.user_id == int(user_id))
    return db.scalar(stmt)


def get_project_detail_for_user(db: Session, project_id: int, user_id: int) -> dict | None:
    project = get_project_for_user(db, project_id, user_id)
    if not project:
        return None
    conversations = list(db.scalars(
        select(Conversation)
        .where(Conversation.user_id == int(user_id), Conversation.project_id == int(project_id))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ).all())
    message_counts: dict[int, int] = {}
    if conversations:
        count_rows = db.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(Message.conversation_id.in_([conversation.id for conversation in conversations]))
            .group_by(Message.conversation_id)
        ).all()
        message_counts = {
            int(conversation_id): int(message_count or 0)
            for conversation_id, message_count in count_rows
        }
    return {
        "project": project,
        "conversations": conversations,
        "message_counts": message_counts,
        "conversation_count": len(conversations),
    }


def rename_project(db: Session, project: Project, name: str) -> Project:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("项目名称不能为空")
    project.name = cleaned
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    db.query(Conversation).where(Conversation.project_id == int(project.id)).update(
        {Conversation.project_id: None},
        synchronize_session=False,
    )
    db.delete(project)
    db.commit()


def create_conversation(
    db: Session,
    *,
    user_id: int,
    mode: str = "text",
    title: str = "新建聊天",
    model: str = "",
    project_id: int | None = None,
) -> Conversation:
    conversation = Conversation(
        user_id=int(user_id),
        project_id=int(project_id) if project_id else None,
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


def move_conversation_to_project(
    db: Session,
    conversation: Conversation,
    project: Project | None,
) -> Conversation:
    conversation.project_id = int(project.id) if project else None
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def delete_conversation(db: Session, conversation: Conversation) -> None:
    db.delete(conversation)
    db.commit()
