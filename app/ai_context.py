"""单次请求内的 AI 日志上下文（request_id、附件 id、image_mode 占位）。"""
from __future__ import annotations

import base64
import uuid
from contextvars import ContextVar, Token
from typing import Optional

from app.logging_config import logger
from app.services.attachment_service import read_attachment_meta_any

_ai_request_id_var: ContextVar[Optional[str]] = ContextVar("ai_request_id", default=None)
_ai_log_attachment_ids_var: ContextVar[Optional[list]] = ContextVar("ai_log_attachment_ids", default=None)
_ai_image_mode_var: ContextVar[str] = ContextVar("ai_image_mode", default="")


def get_ai_request_id() -> str:
    return _ai_request_id_var.get() or "no-req-id"


def get_ai_image_mode() -> str:
    return _ai_image_mode_var.get() or ""


def set_ai_request_context(
    attachment_ids: Optional[list] = None,
    image_mode: Optional[str] = None,
) -> tuple[Token, Token, Token]:
    rid_token = _ai_request_id_var.set(uuid.uuid4().hex[:16])
    att_token = _ai_log_attachment_ids_var.set(attachment_ids if attachment_ids is not None else [])
    im_token = _ai_image_mode_var.set((image_mode or "").strip())
    return rid_token, att_token, im_token


def reset_ai_request_context(rid_token: Token, att_token: Token, im_token: Token) -> None:
    _ai_request_id_var.reset(rid_token)
    _ai_log_attachment_ids_var.reset(att_token)
    _ai_image_mode_var.reset(im_token)


def _log_attachment_image_sizes() -> list[int]:
    sizes: list[int] = []
    for aid in _ai_log_attachment_ids_var.get() or []:
        meta = read_attachment_meta_any(aid) if aid else None
        if meta and meta.get("category") == "image":
            try:
                sizes.append(int(meta.get("size") or 0))
            except (TypeError, ValueError):
                sizes.append(0)
    return sizes


def _decode_data_url_bytes_size(ref_data_url: str) -> int:
    try:
        if ref_data_url.startswith("data:"):
            b64 = ref_data_url.split(",", 1)[1]
        else:
            b64 = ref_data_url
        return len(base64.b64decode(b64, validate=False))
    except Exception:
        return -1


def _ai_log_req(
    path: str,
    model: str,
    prompt_preview: str,
    *,
    has_image: bool = False,
    image_sizes: Optional[list] = None,
    provider: str = "",
) -> None:
    rid = get_ai_request_id()
    sizes = image_sizes if image_sizes is not None else []
    sizes_str = ",".join(str(x) for x in sizes) if sizes else ""
    im = get_ai_image_mode()
    logger.info(
        "[ai-req] request_id=%s path=%s image_mode=%s model=%s provider=%s prompt100=%s has_image=%s image_sizes=%s",
        rid,
        path,
        im,
        model,
        provider,
        (prompt_preview or "")[:100],
        has_image,
        sizes_str,
    )


def _ai_log_resp(
    path: str,
    model: str,
    *,
    success: bool,
    degraded: bool = False,
    status_code: Optional[int] = None,
    error_full: str = "",
    provider: str = "",
) -> None:
    rid = get_ai_request_id()
    im = get_ai_image_mode()
    logger.info(
        "[ai-resp] request_id=%s path=%s image_mode=%s model=%s provider=%s success=%s degraded=%s "
        "status_code=%s error_full=%s",
        rid,
        path,
        im,
        model,
        provider,
        success,
        degraded,
        "" if status_code is None else status_code,
        error_full or "",
    )


def _last_user_text_for_log(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c
        return str(c) if c is not None else ""
    return ""
