"""本地文件：附件元数据、任务 JSON、客户端状态。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import CLIENT_STATE_DIR, TASKS_DIR, UPLOAD_META_DIR


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_json_dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def client_state_file_path(client_state_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", client_state_id or "")
    if not safe_id:
        safe_id = "anonymous"
    return CLIENT_STATE_DIR / f"{safe_id}.json"


def read_attachment_meta(attachment_id: str) -> Optional[dict]:
    meta_path = UPLOAD_META_DIR / f"{attachment_id}.json"
    if not meta_path.exists():
        return None
    try:
        return safe_json_load(meta_path)
    except Exception:
        return None


def task_file_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def save_task_file(task_data: dict) -> None:
    safe_json_dump(task_file_path(task_data["id"]), task_data)


def load_task_file(task_id: str) -> Optional[dict]:
    path = task_file_path(task_id)
    if not path.exists():
        return None
    try:
        return safe_json_load(path)
    except Exception:
        return None


def list_task_files() -> list[Path]:
    return sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)


def normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): normalize_for_hash(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [normalize_for_hash(v) for v in value]
    if isinstance(value, tuple):
        return [normalize_for_hash(v) for v in value]
    return value


def compute_state_fingerprint(state: dict) -> str:
    import hashlib

    normalized = normalize_for_hash(state or {})
    raw = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
