"""模型列表。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.auth import require_auth
from app.services import model_service

router = APIRouter(tags=["models"])


@router.get("/api/models")
def get_models(request: Request):
    require_auth(request)
    return model_service.fetch_models_catalog()
