"""登录与用户服务。"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database_models import User

DEFAULT_BOOTSTRAP_USERNAME = (os.getenv("ACCESS_USERNAME") or "admin").strip() or "admin"
DEFAULT_BOOTSTRAP_PASSWORD = os.getenv("ACCESS_PASSWORD") or "1127"


def hash_password(password: str) -> str:
    # pbkdf2 不依赖 hashlib.scrypt；macOS 部分精简 Python/LibreSSL 下 scrypt 不可用
    return generate_password_hash(password, method="pbkdf2:sha256")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    return check_password_hash(password_hash, password)


def get_user_by_id(db: Session, user_id: int) -> User | None:
    if not user_id:
        return None
    return db.get(User, int(user_id))


def get_user_by_username(db: Session, username: str) -> User | None:
    name = (username or "").strip()
    if not name:
        return None
    stmt = select(User).where(or_(User.username == name, User.phone == name))
    return db.scalar(stmt)


def verify_login(db: Session, username: str, password: str) -> User | None:
    user = get_user_by_username(db, username)
    if not user or not user.is_active or user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def record_login(db: Session, user: User) -> User:
    user.last_login_at = datetime.now()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login_user(request, user: User) -> None:
    request.session["user_id"] = int(user.id)
    request.session["auth_ok"] = True


def logout_user(request) -> None:
    request.session.clear()


def ensure_bootstrap_user(db: Session) -> None:
    existing = get_user_by_username(db, DEFAULT_BOOTSTRAP_USERNAME)
    if existing:
        return

    user = User(
        username=DEFAULT_BOOTSTRAP_USERNAME,
        password_hash=hash_password(DEFAULT_BOOTSTRAP_PASSWORD),
        display_name=DEFAULT_BOOTSTRAP_USERNAME,
        source="local",
        status="active",
        must_change_password=False,
        is_active=True,
    )
    db.add(user)
    db.commit()
