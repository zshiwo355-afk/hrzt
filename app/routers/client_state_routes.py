"""客户端状态同步。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import require_auth
from app.models import ClientStateRequest
from app.services import client_state_service
from app.storage import compute_state_fingerprint

router = APIRouter(tags=["client-state"])


@router.get("/api/client-state")
def get_client_state(request: Request):
    require_auth(request)
    return client_state_service.read_client_state(request)


@router.put("/api/client-state")
def put_client_state(req: ClientStateRequest, request: Request):
    require_auth(request)

    incoming_state = req.state or {}
    incoming_fingerprint = req.fingerprint or compute_state_fingerprint(incoming_state)
    current_payload = client_state_service.read_client_state(request)
    current_updated_at = current_payload.get("updated_at") or ""

    if current_updated_at and req.updated_at and req.updated_at < current_updated_at:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "服务端已有更新版本，已拒绝较旧状态写入。",
                "state": current_payload.get("state") or {},
                "fingerprint": current_payload.get("fingerprint") or "",
                "updated_at": current_updated_at,
            },
        )

    payload = client_state_service.write_client_state(request, incoming_state)
    if payload.get("fingerprint") != incoming_fingerprint:
        payload["client_fingerprint"] = incoming_fingerprint
    return payload
