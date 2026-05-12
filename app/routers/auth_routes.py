"""登录与会话（访问密码已关闭，接口保留兼容）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import bind_login_session, clear_login_session, get_current_user_id
from app.db import get_db
from app.models import LoginRequest
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return {"authenticated": False, "user": None}

    user = auth_service.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        clear_login_session(request)
        return {"authenticated": False, "user": None}

    return {
        "authenticated": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "phone": user.phone or "",
            "department_level1": user.department_level1 or "",
            "department_level2": user.department_level2 or "",
            "must_change_password": bool(user.must_change_password),
        },
    }


@router.post("/login")
def auth_login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = auth_service.verify_login(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误。")

    bind_login_session(request, user.id)
    user = auth_service.record_login(db, user)
    return {
        "ok": True,
        "message": "验证通过",
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name or user.username,
            "phone": user.phone or "",
            "department_level1": user.department_level1 or "",
            "department_level2": user.department_level2 or "",
            "must_change_password": bool(user.must_change_password),
        },
    }


@router.post("/logout")
def auth_logout(request: Request):
    clear_login_session(request)
    return {"ok": True}
