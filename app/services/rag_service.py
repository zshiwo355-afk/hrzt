"""RAG search integration for knowledge-augmented chat."""
from __future__ import annotations

from typing import Any

import requests

from app.config import RAG_CONTEXT_MAX_ITEMS, RAG_DEFAULT_TOP_K
from app.logging_config import logger
from app.models import ChatRequest
from app.providers import rag_client


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


def build_rag_query(req: ChatRequest) -> str:
    override = (req.rag_query or "").strip()
    if override:
        return override
    return (req.prompt or "").strip()


def _pick_list(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []
    for key in ("results", "hits", "items", "data", "documents", "matches", "products"):
        val = raw.get(key)
        if isinstance(val, list):
            return [item for item in val if isinstance(item, dict)]
    if any(key in raw for key in ("best_pdf_hit", "best_image_url", "images", "pdf_reports")):
        return [raw]
    return []


def _pick_first_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text_value(value)
        if cleaned:
            return cleaned
    return ""


def _normalize_images(raw_images: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(raw_images, list):
        return out
    for row in raw_images:
        if isinstance(row, str) and row.strip():
            out.append(row.strip())
            continue
        if not isinstance(row, dict):
            continue
        url = _pick_first_text(
            row.get("url"),
            row.get("image_url"),
            row.get("best_image_url"),
            row.get("src"),
        )
        if url:
            out.append(url)
    return out


def _normalize_pdf_report_titles(raw_reports: Any) -> list[str]:
    titles: list[str] = []
    if not isinstance(raw_reports, list):
        return titles
    for row in raw_reports:
        if isinstance(row, str) and row.strip():
            titles.append(row.strip())
            continue
        if not isinstance(row, dict):
            continue
        title = _pick_first_text(
            row.get("title"),
            row.get("name"),
            row.get("pdf_name"),
            row.get("file_name"),
            row.get("document_name"),
            row.get("supplement_title"),
        )
        if title:
            titles.append(title)
    return titles


def _normalize_pdf_hit(raw_hit: Any) -> dict:
    hit = raw_hit if isinstance(raw_hit, dict) else {}
    if not hit:
        return {}
    page_start = _pick_first_text(hit.get("page_start"), hit.get("page_no"), hit.get("page"), hit.get("page_num"))
    page_end = _pick_first_text(hit.get("page_end"))
    normalized = {
        "pdf_url": _pick_first_text(hit.get("pdf_url")),
        "pdf_path": _pick_first_text(hit.get("pdf_path")),
        "supplement_title": _pick_first_text(hit.get("supplement_title"), hit.get("title"), hit.get("source_file")),
        "page_start": page_start,
        "page_end": page_end,
        "source_file": _pick_first_text(hit.get("source_file")),
        "source_doc_id": _pick_first_text(hit.get("source_doc_id")),
        "source_kind": _pick_first_text(hit.get("source_kind")),
        "chunk_index": _pick_first_text(hit.get("chunk_index")),
    }
    return {key: value for key, value in normalized.items() if value}


def _normalize_pdf_reports(raw_reports: Any) -> list[dict]:
    reports: list[dict] = []
    if not isinstance(raw_reports, list):
        return reports
    for row in raw_reports:
        if not isinstance(row, dict):
            continue
        page_start = _pick_first_text(
            row.get("page_start"),
            row.get("page_no"),
            row.get("page"),
            row.get("page_num"),
        )
        page_end = _pick_first_text(row.get("page_end"))
        normalized = {
            "pdf_url": _pick_first_text(row.get("pdf_url")),
            "pdf_path": _pick_first_text(row.get("pdf_path")),
            "supplement_title": _pick_first_text(
                row.get("supplement_title"),
                row.get("title"),
                row.get("source_file"),
            ),
            "page_start": page_start,
            "page_end": page_end,
            "source_file": _pick_first_text(row.get("source_file")),
            "source_doc_id": _pick_first_text(row.get("source_doc_id")),
            "source_kind": _pick_first_text(row.get("source_kind")),
            "chunk_index": _pick_first_text(row.get("chunk_index")),
        }
        compact = {key: value for key, value in normalized.items() if value}
        if compact:
            reports.append(compact)
    return reports


def normalize_rag_source(item: dict) -> dict:
    best_pdf_hit = item.get("best_pdf_hit")
    best_pdf_hit = best_pdf_hit if isinstance(best_pdf_hit, dict) else {}
    images = _normalize_images(item.get("images"))
    best_image_url = _pick_first_text(item.get("best_image_url"))
    if not best_image_url and images:
        best_image_url = images[0]
    pdf_reports = _normalize_pdf_reports(item.get("pdf_reports"))
    pdf_report_titles = _normalize_pdf_report_titles(item.get("pdf_reports"))
    normalized_best_pdf_hit = _normalize_pdf_hit(best_pdf_hit)
    best_pdf_url = _pick_first_text(
        normalized_best_pdf_hit.get("pdf_url"),
        item.get("pdf_url"),
        *((row.get("pdf_url") for row in pdf_reports) if pdf_reports else ()),
    )

    title = _pick_first_text(
        item.get("title"),
        item.get("name"),
        item.get("doc_title"),
        best_pdf_hit.get("title"),
        best_pdf_hit.get("name"),
        best_pdf_hit.get("file_name"),
        best_pdf_hit.get("supplement_title"),
        item.get("product_id"),
    ) or "知识库来源"
    snippet = _pick_first_text(
        item.get("best_text"),
        item.get("snippet"),
        item.get("summary"),
        item.get("abstract"),
        item.get("content_preview"),
        item.get("text"),
        best_pdf_hit.get("snippet"),
        best_pdf_hit.get("summary"),
        best_pdf_hit.get("excerpt"),
        best_pdf_hit.get("text"),
    )
    page_start = _pick_first_text(
        item.get("page_start"),
        item.get("page_no"),
        item.get("page"),
        item.get("page_num"),
        normalized_best_pdf_hit.get("page_start"),
    )
    page_end = _pick_first_text(item.get("page_end"), normalized_best_pdf_hit.get("page_end"))
    page_label = ""
    if page_start and page_end and page_end != page_start:
        page_label = f"第{page_start}-{page_end}页"
    elif page_start:
        page_label = f"第{page_start}页"
    supplement_title = _pick_first_text(
        normalized_best_pdf_hit.get("supplement_title"),
        item.get("supplement_title"),
        *((row.get("supplement_title") for row in pdf_reports) if pdf_reports else ()),
    )
    source_type = "mixed" if best_image_url and (best_pdf_hit or pdf_report_titles) else "image" if best_image_url else "pdf"
    return {
        "title": title,
        "snippet": snippet,
        "page_label": page_label,
        "page_start": page_start,
        "page_end": page_end,
        "supplement_title": supplement_title,
        "best_image_url": best_image_url,
        "images": images[:3],
        "image_count": len(images),
        "best_pdf_url": best_pdf_url,
        "best_pdf_hit": normalized_best_pdf_hit,
        "pdf_reports": pdf_reports[:5],
        "pdf_report_titles": pdf_report_titles[:3],
        "source_type": source_type,
    }


def normalize_rag_sources(raw: Any) -> list[dict]:
    rows = _pick_list(raw)
    return [normalize_rag_source(row) for row in rows]


def build_rag_context_text(sources: list[dict], *, context_limit: int = RAG_CONTEXT_MAX_ITEMS) -> str:
    if not sources:
        return ""
    sections: list[str] = []
    limit = max(1, context_limit)
    for idx, src in enumerate(sources[:limit], start=1):
        lines = [f"【来源{idx}】", f"标题：{src.get('title') or '知识库来源'}"]
        snippet = (src.get("snippet") or "").strip()
        if snippet:
            lines.append(f"摘要：{snippet}")
        page_label = (src.get("page_label") or "").strip()
        if page_label:
            lines.append(f"页码：{page_label}")
        pdf_titles = src.get("pdf_report_titles") or []
        if pdf_titles:
            lines.append("相关文档：" + "、".join(pdf_titles))
        best_image_url = (src.get("best_image_url") or "").strip()
        if best_image_url:
            lines.append(f"主图：{best_image_url}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections).strip()


def build_rag_bundle(req: ChatRequest) -> dict:
    if not req.use_rag:
        return {
            "used": False,
            "query": "",
            "sources": [],
            "context_text": "",
            "note": "",
            "rag_status": "",
        }

    query = build_rag_query(req)
    if not query:
        return {
            "used": False,
            "query": "",
            "sources": [],
            "context_text": "",
            "note": "未检索到相关知识库内容",
            "rag_status": "empty",
        }

    try:
        resp = rag_client.rag_search(query, top_k=RAG_DEFAULT_TOP_K)
        resp.raise_for_status()
        body = resp.json()
    except requests.exceptions.Timeout as exc:
        logger.warning("[rag-search-timeout] query=%r error=%r", query[:200], exc)
        return {
            "used": False,
            "query": query,
            "sources": [],
            "context_text": "",
            "note": "知识库连接超时，请稍后重试",
            "rag_status": "timeout",
        }
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning("[rag-search-error] query=%r error=%r", query[:200], exc)
        return {
            "used": False,
            "query": query,
            "sources": [],
            "context_text": "",
            "note": "知识库服务暂不可用",
            "rag_status": "error",
        }

    try:
        sources = normalize_rag_sources(body)
    except Exception as exc:
        logger.warning("[rag-normalize-error] query=%r error=%r", query[:200], exc)
        return {
            "used": False,
            "query": query,
            "sources": [],
            "context_text": "",
            "note": "知识库服务暂不可用",
            "rag_status": "error",
        }

    context_sources = sources[: max(1, RAG_CONTEXT_MAX_ITEMS)]
    context_text = build_rag_context_text(context_sources, context_limit=RAG_CONTEXT_MAX_ITEMS)
    rag_status = "hit" if sources else "empty"
    note = ""
    if rag_status == "empty":
        note = "未检索到相关知识库内容"
    return {
        "used": rag_status == "hit" and bool(context_text),
        "query": query,
        "sources": sources,
        "context_text": context_text,
        "note": note,
        "rag_status": rag_status,
    }
