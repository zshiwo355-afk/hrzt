"""RAG HTTP client."""
from __future__ import annotations

from typing import Optional

import requests

from app.config import RAG_BASE_URL, RAG_SEARCH_TIMEOUT_SECONDS

_rag_http_session: Optional[requests.Session] = None


def _get_rag_http_session() -> requests.Session:
    global _rag_http_session
    if _rag_http_session is None:
        session = requests.Session()
        session.trust_env = False
        _rag_http_session = session
    return _rag_http_session


def rag_base_url() -> str:
    return RAG_BASE_URL


def rag_health(timeout: int = 5) -> requests.Response:
    session = _get_rag_http_session()
    return session.get(
        f"{rag_base_url()}/api/rag/health",
        timeout=timeout,
        proxies={"http": None, "https": None},
    )


def rag_search(query: str, *, top_k: int, timeout: int = RAG_SEARCH_TIMEOUT_SECONDS) -> requests.Response:
    session = _get_rag_http_session()
    return session.post(
        f"{rag_base_url()}/api/rag/search",
        json={"query": query, "top_k": int(top_k)},
        timeout=timeout,
        proxies={"http": None, "https": None},
    )
