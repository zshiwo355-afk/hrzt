"""聊天记录：按 history_user_id 存 OSS（index + conversations）。"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Optional

from app.config import OSS_PREFIX_CHAT_HISTORY, oss_configured
from app.logging_config import logger
from app.providers import oss


def _index_key(user_id: str) -> str:
    return f"{OSS_PREFIX_CHAT_HISTORY}/users/{user_id}/index.json"


def _conversation_key(user_id: str, conversation_id: str) -> str:
    return f"{OSS_PREFIX_CHAT_HISTORY}/users/{user_id}/conversations/{conversation_id}.json"


def _normalize_index(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _conversation_qualifies_for_index(doc: dict[str, Any]) -> bool:
    """有第一条有效保存内容后再进入 index（空会话仅占 OSS 文件，不进列表索引）。"""
    msgs = doc.get("messages")
    if isinstance(msgs, list) and len(msgs) > 0:
        return True
    if str(doc.get("summary") or "").strip():
        return True
    return False


def _index_row_nonempty(row: dict[str, Any]) -> bool:
    """列表 API 是否返回该行（兼容旧 index 无 message_count / has_summary）。"""
    if row.get("has_summary"):
        return True
    mc = row.get("message_count")
    if mc is None:
        return True
    try:
        return int(mc) > 0
    except (TypeError, ValueError):
        return True


def list_conversation_index(user_id: str, mode: Optional[str] = None) -> list[dict[str, Any]]:
    if not oss_configured():
        return []
    rows = _normalize_index(oss.read_json(_index_key(user_id)))
    rows = [r for r in rows if _index_row_nonempty(r)]
    if mode in ("text", "image", "video"):
        rows = [r for r in rows if str(r.get("mode") or "text") == mode]

    def _ts(row: dict[str, Any]) -> float:
        for k in ("updated_at", "created_at"):
            v = row.get(k)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                if v.isdigit():
                    return float(v)
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000
                except Exception:
                    continue
        return 0.0

    rows.sort(key=_ts, reverse=True)
    return rows


def load_conversation_doc(user_id: str, conversation_id: str) -> Optional[dict[str, Any]]:
    if not oss_configured():
        return None
    doc = oss.read_json(_conversation_key(user_id, conversation_id))
    if not isinstance(doc, dict):
        return None
    doc.setdefault("id", conversation_id)
    doc.setdefault("messages", [])
    return doc


def _save_index(user_id: str, rows: list[dict[str, Any]]) -> bool:
    return oss.write_json(_index_key(user_id), rows)


def _upsert_index_row(user_id: str, doc: dict[str, Any]) -> None:
    cid = str(doc.get("id") or "")
    if not cid:
        return
    if not _conversation_qualifies_for_index(doc):
        _remove_index_row(user_id, cid)
        return
    rows = _normalize_index(oss.read_json(_index_key(user_id)))
    title = str(doc.get("title") or "新建聊天")
    mode = str(doc.get("mode") or "text")
    created = doc.get("created_at")
    updated = doc.get("updated_at")
    messages = doc.get("messages") if isinstance(doc.get("messages"), list) else []
    has_summary = bool(str(doc.get("summary") or "").strip())
    row = {
        "id": cid,
        "title": title,
        "mode": mode,
        "created_at": created,
        "updated_at": updated,
        "message_count": len(messages),
        "has_summary": has_summary,
    }
    others = [r for r in rows if str(r.get("id")) != cid]
    others.insert(0, row)
    _save_index(user_id, others)


def _remove_index_row(user_id: str, conversation_id: str) -> None:
    rows = _normalize_index(oss.read_json(_index_key(user_id)))
    rows = [r for r in rows if str(r.get("id")) != conversation_id]
    _save_index(user_id, rows)


def create_conversation(
    user_id: str,
    *,
    mode: str,
    title: str = "新建聊天",
    model: str = "",
    conversation_id: Optional[str] = None,
) -> dict[str, Any]:
    if not oss_configured():
        raise RuntimeError("OSS 未配置，无法创建会话。")
    cid = conversation_id or f"conv_{uuid.uuid4().hex}"
    now_ms = int(time.time() * 1000)
    doc: dict[str, Any] = {
        "id": cid,
        "user_id": user_id,
        "title": title,
        "mode": mode if mode in ("text", "image", "video") else "text",
        "created_at": now_ms,
        "updated_at": now_ms,
        "model": model,
        "draft": "",
        "size": "1024x1024" if mode == "image" else None,
        "image_mode": None,
        "summary": "",
        "summaryMessageCount": 0,
        "attachments": [],
        "messages": [],
    }
    if not oss.write_json(_conversation_key(user_id, cid), doc):
        raise RuntimeError("写入会话失败。")
    # 空白会话不写 index.json，首次产生消息/摘要后由 save 写入索引
    return doc


def save_conversation_doc(user_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    if not oss_configured():
        raise RuntimeError("OSS 未配置。")
    cid = str(doc.get("id") or "")
    if not cid:
        raise ValueError("会话 id 不能为空")
    doc["user_id"] = user_id
    if not oss.write_json(_conversation_key(user_id, cid), doc):
        raise RuntimeError("保存会话失败。")
    _upsert_index_row(user_id, doc)
    return doc


def delete_conversation(user_id: str, conversation_id: str) -> bool:
    if not oss_configured():
        return False
    oss.delete_object(_conversation_key(user_id, conversation_id))
    _remove_index_row(user_id, conversation_id)
    return True


def append_messages(user_id: str, conversation_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    doc = load_conversation_doc(user_id, conversation_id)
    if not doc:
        raise FileNotFoundError("会话不存在")
    arr = doc.get("messages")
    if not isinstance(arr, list):
        arr = []
    for m in messages:
        if isinstance(m, dict):
            arr.append(m)
    doc["messages"] = arr
    doc["updated_at"] = int(time.time() * 1000)
    return save_conversation_doc(user_id, doc)
