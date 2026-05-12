"""访问会话（已取消页面访问密码，保留会话标记供 WebSocket / 既有逻辑使用）。"""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException, Request

from app.config import OSS_HISTORY_USER_ID

SESSION_USER_ID_KEY = "user_id"


def get_current_user_id(request: Request) -> int | None:
    raw = request.session.get(SESSION_USER_ID_KEY)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def bind_login_session(request: Request, user_id: int) -> None:
    request.session[SESSION_USER_ID_KEY] = int(user_id)
    request.session["auth_ok"] = True


def clear_login_session(request: Request) -> None:
    request.session.clear()


def require_auth(request: Request) -> int:
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录。")
    request.session["auth_ok"] = True
    return user_id


def get_client_state_id(request: Request) -> str:
    current = request.session.get("client_state_id")
    if current:
        return str(current)

    current = uuid.uuid4().hex
    request.session["client_state_id"] = current
    return current


_BROWSER_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,128}$")


def resolve_history_user_id(request: Request) -> str:
    """优先浏览器唯一 ID；否则回退 OSS_HISTORY_USER_ID / 会话 client_state / 密码派生。"""
    raw = (request.headers.get("X-History-Browser-Id") or request.headers.get("x-history-browser-id") or "").strip()
    if raw and _BROWSER_ID_RE.match(raw):
        return f"browser_{raw}"

    if OSS_HISTORY_USER_ID:
        return OSS_HISTORY_USER_ID

    return f"client_{get_client_state_id(request)}"
