"""联网搜索 HTTP client。旧第三方 provider 路线，当前文本主链已停用。"""
from __future__ import annotations

from typing import Optional

import requests

from app.config import (
    WEB_SEARCH_API_KEY,
    WEB_SEARCH_API_KEY_HEADER,
    WEB_SEARCH_API_KEY_PREFIX,
    WEB_SEARCH_BASE_URL,
    WEB_SEARCH_PATH,
    WEB_SEARCH_TIMEOUT_SECONDS,
    web_search_configured,
)

_search_http_session: Optional[requests.Session] = None


def _get_search_http_session() -> requests.Session:
    global _search_http_session
    if _search_http_session is None:
        session = requests.Session()
        session.trust_env = False
        _search_http_session = session
    return _search_http_session


def search_base_url() -> str:
    return WEB_SEARCH_BASE_URL


def search_path() -> str:
    return WEB_SEARCH_PATH


def _build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if WEB_SEARCH_API_KEY:
        value = f"{WEB_SEARCH_API_KEY_PREFIX}{WEB_SEARCH_API_KEY}"
        headers[WEB_SEARCH_API_KEY_HEADER] = value
    return headers


def search_query(
    query: str,
    *,
    top_k: int,
    timeout: int = WEB_SEARCH_TIMEOUT_SECONDS,
) -> requests.Response:
    if not web_search_configured():
        raise RuntimeError("WEB_SEARCH_BASE_URL 未配置")

    session = _get_search_http_session()
    return session.post(
        f"{search_base_url()}{search_path()}",
        headers=_build_headers(),
        json={"query": query, "top_k": int(top_k)},
        timeout=timeout,
        proxies={"http": None, "https": None},
    )
