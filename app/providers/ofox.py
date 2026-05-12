"""OFOX HTTP：统一 Session，禁止裸 requests 调上游。"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests

from app.config import OFOX_API_KEY, OFOX_BASE_URL
from app.logging_config import logger

_ofox_http_session: Optional[requests.Session] = None


def _get_ofox_http_session() -> requests.Session:
    global _ofox_http_session
    if _ofox_http_session is None:
        s = requests.Session()
        s.trust_env = False
        _ofox_http_session = s
    return _ofox_http_session


def _ofox_transient_dns_or_connect(exc: BaseException) -> bool:
    """路由器 DNS 偶发失败时，短暂重试往往可恢复。"""
    s = repr(exc).lower()
    needles = (
        "nameresolutionerror",
        "nodename nor servname",
        "failed to resolve",
        "gaierror",
        "temporary failure in name resolution",
        "connection refused",
        "connection reset",
        "newconnectionerror",
    )
    return any(n in s for n in needles)


def ofox_request(method: str, url: str, **kwargs) -> requests.Response:
    session = _get_ofox_http_session()
    req_kw = dict(kwargs)
    req_kw["proxies"] = {"http": None, "https": None}
    if "timeout" not in req_kw:
        req_kw["timeout"] = 60
    logger.info(
        "[ofox-http] trust_env=%r proxies=%r method=%s url=%s",
        getattr(session, "trust_env", None),
        req_kw.get("proxies"),
        method.upper(),
        (url or "")[:160],
    )
    delays = (0.6, 1.5, 3.0)
    for attempt in range(4):
        if attempt:
            time.sleep(delays[attempt - 1])
            logger.info(
                "[ofox-http] retry_after_dns_or_connect attempt=%s url=%s",
                attempt + 1,
                (url or "")[:120],
            )
        try:
            return session.request(method.upper(), url, **req_kw)
        except requests.exceptions.RequestException as e:
            if attempt < 3 and _ofox_transient_dns_or_connect(e):
                continue
            raise


def extract_error_message_from_response(resp: requests.Response) -> str:
    content_type = (resp.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            data = resp.json()
            if isinstance(data, dict):
                for key in ("detail", "message", "error"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                return json.dumps(data, ensure_ascii=False)[:800]
        except Exception:
            pass

    text = (resp.text or "").strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:800] if text else "上游服务没有返回可读错误信息。"


def ofox_base_url() -> str:
    return OFOX_BASE_URL


def ofox_root_url() -> str:
    base = ofox_base_url().rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


def ofox_api_key() -> str:
    return OFOX_API_KEY or ""


def ofox_json_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {ofox_api_key()}",
        "Content-Type": "application/json",
    }


def ofox_gemini_headers() -> dict[str, str]:
    return {
        "x-goog-api-key": ofox_api_key(),
        "Content-Type": "application/json",
    }


def ofox_anthropic_headers() -> dict[str, str]:
    key = ofox_api_key()
    return {
        "x-api-key": key,
        "Authorization": f"Bearer {key}",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def ofox_chat_completions_url() -> str:
    return f"{ofox_base_url()}/chat/completions"


def ofox_responses_url() -> str:
    return f"{ofox_base_url()}/responses"


def ofox_anthropic_messages_url() -> str:
    return f"{ofox_root_url()}/anthropic/v1/messages"
