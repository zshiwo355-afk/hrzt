"""浏览器端状态同步（JSON 文件）。"""
from __future__ import annotations

from fastapi import Request

from app.auth import get_client_state_id
from app.storage import (
    client_state_file_path,
    compute_state_fingerprint,
    now_iso,
    safe_json_dump,
    safe_json_load,
)


def read_client_state(request: Request) -> dict:
    state_id = get_client_state_id(request)
    path = client_state_file_path(state_id)
    if not path.exists():
        return {"state": {}, "fingerprint": "", "updated_at": ""}

    try:
        payload = safe_json_load(path)
    except Exception:
        return {"state": {}, "fingerprint": "", "updated_at": ""}

    return {
        "state": payload.get("state") or {},
        "fingerprint": payload.get("fingerprint") or "",
        "updated_at": payload.get("updated_at") or "",
    }


def write_client_state(request: Request, state: dict) -> dict:
    state_id = get_client_state_id(request)
    payload = {
        "state": state or {},
        "fingerprint": compute_state_fingerprint(state or {}),
        "updated_at": now_iso(),
    }
    safe_json_dump(client_state_file_path(state_id), payload)
    return payload
