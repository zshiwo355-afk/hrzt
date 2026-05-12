"""数据库 ORM 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(32), unique=True, index=True, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    department_level1: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    department_level2: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    external_user_id: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")
    messages: Mapped[list["Message"]] = relationship(back_populates="user")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="新建聊天", nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="text", nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        order_by="Message.id",
        cascade="all, delete-orphan",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attachments_json: Mapped[Optional[Union[list, dict]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    user: Mapped["User"] = relationship(back_populates="messages")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    artifact_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="queued")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    reasoning_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size: Mapped[str] = mapped_column(String(32), nullable=False, default="1024x1024")
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    assistant_message_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    attachment_ids_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    history_messages_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    use_rag: Mapped[bool] = mapped_column(default=False, nullable=False)
    use_web_search: Mapped[bool] = mapped_column(default=False, nullable=False)
    image_mode: Mapped[str] = mapped_column(String(64), nullable=False, default="auto_api_passthrough")
    image_intent: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    reference_source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    image_intent_confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="0")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    progress_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    history_user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    stored_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    storage: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="local")
    oss_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suffix: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="application/octet-stream")
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="document")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="upload")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
