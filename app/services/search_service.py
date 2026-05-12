"""联网搜索：旧第三方 provider 路线，当前文本主链已停用，暂保留作历史兜底代码。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

from app.config import (
    WEB_SEARCH_CONTEXT_MAX_ITEMS,
    WEB_SEARCH_TOP_K,
    web_search_configured,
)
from app.logging_config import logger
from app.models import ChatRequest
from app.providers import search_client


def _clean_text_value(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.lower() in {"null", "none", "nan"}:
        return ""
    return cleaned


def _pick_first_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text_value(value)
        if cleaned:
            return cleaned
    return ""


def _pick_list(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []

    web_obj = raw.get("web")
    if isinstance(web_obj, dict):
        for key in ("results", "hits", "items", "organic_results"):
            val = web_obj.get(key)
            if isinstance(val, list):
                return [item for item in val if isinstance(item, dict)]

    for key in ("results", "hits", "items", "data", "organic_results", "documents", "matches"):
        val = raw.get(key)
        if isinstance(val, list):
            return [item for item in val if isinstance(item, dict)]

    if any(key in raw for key in ("title", "url", "link", "snippet", "summary")):
        return [raw]
    return []


def _normalize_url(value: Any) -> str:
    url = _pick_first_text(value)
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _derive_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def build_search_query(req: ChatRequest) -> str:
    return (req.prompt or "").strip()


def normalize_search_source(item: dict) -> dict:
    url = _normalize_url(
        _pick_first_text(
            item.get("url"),
            item.get("link"),
            item.get("href"),
            item.get("source_url"),
        )
    )
    domain = _pick_first_text(item.get("domain"), item.get("site_name"), _derive_domain(url))
    title = _pick_first_text(
        item.get("title"),
        item.get("name"),
        item.get("headline"),
        item.get("source_title"),
    ) or "网页来源"
    snippet = _pick_first_text(
        item.get("snippet"),
        item.get("summary"),
        item.get("description"),
        item.get("content"),
        item.get("text"),
        item.get("abstract"),
    )
    published_at = _pick_first_text(
        item.get("published_at"),
        item.get("publishedAt"),
        item.get("date"),
        item.get("time"),
    )
    meta_parts = [part for part in (domain, published_at) if part]
    return {
        "source_type": "web",
        "title": title,
        "snippet": snippet,
        "url": url,
        "domain": domain,
        "published_at": published_at,
        "meta_label": " · ".join(meta_parts),
    }


def normalize_search_sources(raw: Any) -> list[dict]:
    rows = _pick_list(raw)
    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        item = normalize_search_source(row)
        dedupe_key = (item.get("title") or "", item.get("url") or "")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(item)
    return normalized


def build_web_search_context_text(
    sources: list[dict],
    *,
    context_limit: int = WEB_SEARCH_CONTEXT_MAX_ITEMS,
) -> str:
    if not sources:
        return ""
    sections: list[str] = []
    limit = max(1, context_limit)
    for idx, src in enumerate(sources[:limit], start=1):
        lines = [f"【搜索结果{idx}】", f"标题：{src.get('title') or '网页来源'}"]
        domain = (src.get("domain") or "").strip()
        if domain:
            lines.append(f"来源：{domain}")
        snippet = (src.get("snippet") or "").strip()
        if snippet:
            lines.append(f"摘要：{snippet}")
        url = (src.get("url") or "").strip()
        if url:
            lines.append(f"链接：{url}")
        sections.append("\n".join(lines))
    return "\n\n".join(section for section in sections if section).strip()


def build_web_search_bundle(req: ChatRequest) -> dict:
    if not req.use_web_search:
        return {
            "used": False,
            "query": "",
            "sources": [],
            "context_text": "",
            "note": "",
            "search_status": "",
        }

    query = build_search_query(req)
    if not query:
        return {
            "used": False,
            "query": "",
            "sources": [],
            "context_text": "",
            "note": "未检索到相关联网搜索内容",
            "search_status": "empty",
        }

    if not web_search_configured():
        return {
            "used": False,
            "query": query,
            "sources": [],
            "context_text": "",
            "note": "联网搜索服务未配置，已按普通对话回答",
            "search_status": "error",
        }

    try:
        resp = search_client.search_query(query, top_k=WEB_SEARCH_TOP_K)
        resp.raise_for_status()
        raw = resp.json()
        sources = normalize_search_sources(raw)
        if not sources:
            return {
                "used": True,
                "query": query,
                "sources": [],
                "context_text": "",
                "note": "未检索到相关联网搜索内容",
                "search_status": "empty",
            }
        return {
            "used": True,
            "query": query,
            "sources": sources,
            "context_text": build_web_search_context_text(sources),
            "note": "",
            "search_status": "hit",
        }
    except requests.exceptions.Timeout as exc:
        logger.warning("[web-search-timeout] query=%r error=%r", query, exc)
        return {
            "used": False,
            "query": query,
            "sources": [],
            "context_text": "",
            "note": "联网搜索超时，已按普通对话回答",
            "search_status": "timeout",
        }
    except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
        logger.warning("[web-search-error] query=%r error=%r", query, exc)
        return {
            "used": False,
            "query": query,
            "sources": [],
            "context_text": "",
            "note": "联网搜索服务暂不可用，已按普通对话回答",
            "search_status": "error",
        }
