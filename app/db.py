"""SQLAlchemy 引擎与会话。"""
from __future__ import annotations

import os
from typing import Generator
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_SessionLocal = None


def build_database_url() -> str:
    direct = (os.getenv("DATABASE_URL") or "").strip()
    if direct:
        return direct

    host = (os.getenv("MYSQL_HOST") or "").strip()
    port = (os.getenv("MYSQL_PORT") or "").strip()
    user = (os.getenv("MYSQL_USER") or "").strip()
    password = os.getenv("MYSQL_PASSWORD") or ""
    database = (os.getenv("MYSQL_DATABASE") or "").strip()

    missing = [
        name
        for name, value in (
            ("MYSQL_HOST", host),
            ("MYSQL_PORT", port),
            ("MYSQL_USER", user),
            ("MYSQL_DATABASE", database),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"数据库配置缺失：{', '.join(missing)}")

    return (
        "mysql+pymysql://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}?charset=utf8mb4"
    )


def get_engine():
    global _engine
    if _engine is None:
        from app.config import DB_MAX_OVERFLOW, DB_POOL_SIZE, DB_POOL_TIMEOUT_SECONDS

        _engine = create_engine(
            build_database_url(),
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=DB_POOL_SIZE,
            max_overflow=DB_MAX_OVERFLOW,
            pool_timeout=DB_POOL_TIMEOUT_SECONDS,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def ensure_user_schema() -> None:
    """Keep the lightweight personnel columns present without introducing Alembic yet."""
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return

    columns = {col["name"] for col in inspector.get_columns("users")}
    column_sql = {
        "phone": "ALTER TABLE users ADD COLUMN phone VARCHAR(32) NULL",
        "department_level1": "ALTER TABLE users ADD COLUMN department_level1 VARCHAR(128) NULL",
        "department_level2": "ALTER TABLE users ADD COLUMN department_level2 VARCHAR(128) NULL",
        "external_user_id": "ALTER TABLE users ADD COLUMN external_user_id VARCHAR(128) NULL",
        "source": "ALTER TABLE users ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'local'",
        "status": "ALTER TABLE users ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'active'",
        "must_change_password": "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE",
        "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at DATETIME NULL",
    }

    with engine.begin() as conn:
        for name, ddl in column_sql.items():
            if name not in columns:
                conn.execute(text(ddl))

    inspector = inspect(engine)
    indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    indexes.update({uc["name"] for uc in inspector.get_unique_constraints("users") if uc.get("name")})
    index_sql = {
        "ix_users_phone": "CREATE UNIQUE INDEX ix_users_phone ON users (phone)",
        "ix_users_department_level1": "CREATE INDEX ix_users_department_level1 ON users (department_level1)",
        "ix_users_department_level2": "CREATE INDEX ix_users_department_level2 ON users (department_level2)",
        "ix_users_status": "CREATE INDEX ix_users_status ON users (status)",
        "ux_users_external_user_id": "CREATE UNIQUE INDEX ux_users_external_user_id ON users (external_user_id)",
    }
    with engine.begin() as conn:
        for name, ddl in index_sql.items():
            if name not in indexes:
                conn.execute(text(ddl))


def ensure_conversation_message_indexes() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("conversations") or not inspector.has_table("messages"):
        return

    conv_indexes = {idx["name"] for idx in inspector.get_indexes("conversations")}
    msg_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}
    with engine.begin() as conn:
        if "ix_conversations_user_updated" not in conv_indexes:
            conn.execute(
                text(
                    "CREATE INDEX ix_conversations_user_updated "
                    "ON conversations (user_id, updated_at, id)"
                )
            )
        if "ix_messages_conversation_id_id" not in msg_indexes:
            conn.execute(
                text(
                    "CREATE INDEX ix_messages_conversation_id_id "
                    "ON messages (conversation_id, id)"
                )
            )


def ensure_generation_task_indexes() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("generation_tasks"):
        return

    columns = {col["name"] for col in inspector.get_columns("generation_tasks")}
    column_sql = {
        "image_intent": "ALTER TABLE generation_tasks ADD COLUMN image_intent VARCHAR(32) NOT NULL DEFAULT ''",
        "reference_source": "ALTER TABLE generation_tasks ADD COLUMN reference_source VARCHAR(64) NOT NULL DEFAULT ''",
        "image_intent_confidence": (
            "ALTER TABLE generation_tasks ADD COLUMN image_intent_confidence VARCHAR(16) NOT NULL DEFAULT '0'"
        ),
    }
    with engine.begin() as conn:
        for name, ddl in column_sql.items():
            if name not in columns:
                conn.execute(text(ddl))

    inspector = inspect(engine)
    indexes = {idx["name"] for idx in inspector.get_indexes("generation_tasks")}
    index_sql = {
        "ix_generation_tasks_status_created": (
            "CREATE INDEX ix_generation_tasks_status_created "
            "ON generation_tasks (status, created_at)"
        ),
        "ix_generation_tasks_assistant_status": (
            "CREATE INDEX ix_generation_tasks_assistant_status "
            "ON generation_tasks (assistant_message_id, status)"
        ),
        "ix_generation_tasks_conversation_created": (
            "CREATE INDEX ix_generation_tasks_conversation_created "
            "ON generation_tasks (conversation_id, created_at)"
        ),
    }
    with engine.begin() as conn:
        for name, ddl in index_sql.items():
            if name not in indexes:
                conn.execute(text(ddl))


def ensure_attachment_indexes() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    if not inspector.has_table("attachments"):
        return
    indexes = {idx["name"] for idx in inspector.get_indexes("attachments")}
    index_sql = {
        "ix_attachments_user_created": "CREATE INDEX ix_attachments_user_created ON attachments (user_id, created_at)",
        "ix_attachments_conversation_created": (
            "CREATE INDEX ix_attachments_conversation_created ON attachments (conversation_id, created_at)"
        ),
        "ix_attachments_task_id": "CREATE INDEX ix_attachments_task_id ON attachments (task_id)",
        "ix_attachments_category_created": "CREATE INDEX ix_attachments_category_created ON attachments (category, created_at)",
    }
    with engine.begin() as conn:
        for name, ddl in index_sql.items():
            if name not in indexes:
                conn.execute(text(ddl))


def init_db() -> None:
    from app.database_models import Base
    from app.services.auth_service import ensure_bootstrap_user

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    ensure_user_schema()
    ensure_conversation_message_indexes()
    ensure_generation_task_indexes()
    ensure_attachment_indexes()

    with get_session_factory()() as db:
        ensure_bootstrap_user(db)
