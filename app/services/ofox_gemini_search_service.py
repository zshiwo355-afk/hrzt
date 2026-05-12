"""OFOX Gemini Native：googleSearch Grounding 的文本搜索接入。"""
from __future__ import annotations

import json
from typing import Any, Iterator
from urllib.parse import urlparse

import requests
from fastapi import HTTPException

from app.ai_context import (
    _ai_log_req,
    _ai_log_resp,
    _last_user_text_for_log,
    _log_attachment_image_sizes,
)
from app.config import TEXT_TIMEOUT_SECONDS
from app.providers import ofox
from app.providers.ofox_gemini import (
    gemini_native_generate_content_endpoint,
    gemini_native_stream_generate_content_endpoint,
)
from app.services import model_capability_service
from app.services.attachment_service import clean_response_text, extract_text_from_content

GEMINI_WEB_SEARCH_PUBLIC_ID = "google/gemini-3.1-pro"
GEMINI_WEB_SEARCH_NATIVE_ID = "google/gemini-3.1-pro-preview"
GEMINI_WEB_SEARCH_SUPPORTED_IDS = {
    GEMINI_WEB_SEARCH_PUBLIC_ID,
    GEMINI_WEB_SEARCH_NATIVE_ID,
}


def supports_gemini_builtin_web_search(model: str) -> bool:
    return (model or "").strip().lower() in GEMINI_WEB_SEARCH_SUPPORTED_IDS


def gemini_native_search_model_id(model: str) -> str:
    if supports_gemini_builtin_web_search(model):
        return GEMINI_WEB_SEARCH_NATIVE_ID
    return (model or "").strip()


def _input_to_prompt(input_payload: str | list[dict]) -> str:
    if isinstance(input_payload, str):
        return input_payload.strip()
    if not isinstance(input_payload, list):
        return str(input_payload or "").strip()

    lines: list[str] = []
    role_map = {"system": "系统", "user": "用户", "assistant": "助手"}
    for item in input_payload:
        if not isinstance(item, dict):
            continue
        role = role_map.get(str(item.get("role") or "").strip().lower(), "消息")
        text = extract_text_from_content(item.get("content"))
        text = (text or "").strip()
        if text:
            lines.append(f"{role}：{text}")
    return "\n\n".join(lines).strip()


def _gemini_thinking_level(reasoning_mode: str | None) -> str:
    """Gemini native API uses thinkingLevel for Gemini 3 models; Pro supports low/high."""
    mode = model_capability_service.normalize_reasoning_mode(reasoning_mode)
    if mode == model_capability_service.REASONING_MODE_INSTANT:
        return "low"
    if mode in (
        model_capability_service.REASONING_MODE_THINKING,
        model_capability_service.REASONING_MODE_ADVANCED,
    ):
        return "high"
    return ""


def _build_gemini_search_payload(
    input_payload: str | list[dict],
    *,
    reasoning_mode: str | None = None,
) -> dict[str, Any]:
    prompt = _input_to_prompt(input_payload)
    payload: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt,
                    }
                ],
            }
        ],
        "tools": [
            {"googleSearch": {}},
        ],
    }
    thinking_level = _gemini_thinking_level(reasoning_mode)
    if thinking_level:
        payload["generationConfig"] = {
            "thinkingConfig": {
                "thinkingLevel": thinking_level,
            }
        }
    return payload


def _text_parts_from_candidate(candidate: dict) -> list[str]:
    content = candidate.get("content")
    if not isinstance(content, dict):
        return []
    parts = content.get("parts")
    if not isinstance(parts, list):
        return []
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    return texts


def _extract_candidate_text(data: dict) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return ""
    texts: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            texts.extend(_text_parts_from_candidate(candidate))
    return "".join(texts)


def _extract_grounding_metadata(data: dict) -> dict:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            grounding = candidate.get("groundingMetadata")
            if isinstance(grounding, dict):
                return grounding
    return {}


def _derive_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _web_source(title: str, url: str, snippet: str = "", meta_label: str = "") -> dict:
    domain = _derive_domain(url)
    clean_title = (title or "网页来源").strip() or "网页来源"
    return {
        "source_type": "web",
        "title": clean_title,
        "snippet": (snippet or "").strip(),
        "url": (url or "").strip(),
        "domain": domain,
        "published_at": "",
        "meta_label": meta_label or (clean_title if clean_title != "网页来源" else domain),
    }


def _add_source_unique(sources: list[dict], seen: set[tuple[str, str]], source: dict | None) -> None:
    if not source:
        return
    key = (str(source.get("title") or ""), str(source.get("url") or ""))
    if key in seen:
        return
    seen.add(key)
    sources.append(source)


def _extract_grounding_sources(grounding: dict, data: dict | None = None) -> list[dict]:
    chunks = grounding.get("groundingChunks")
    supports = grounding.get("groundingSupports")
    snippet_map: dict[int, list[str]] = {}
    if isinstance(supports, list):
        for item in supports:
            if not isinstance(item, dict):
                continue
            segment = item.get("segment")
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            indices = item.get("groundingChunkIndices")
            if not isinstance(indices, list):
                continue
            for idx in indices:
                if isinstance(idx, int):
                    snippet_map.setdefault(idx, []).append(text)

    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(chunks, list):
        for idx, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            web = chunk.get("web")
            if not isinstance(web, dict):
                continue
            title = str(web.get("title") or "网页来源").strip() or "网页来源"
            url = str(web.get("uri") or web.get("url") or "").strip()
            snippets = snippet_map.get(idx) or []
            snippet = "\n".join(snippets[:2]).strip()
            _add_source_unique(sources, seen, _web_source(title, url, snippet))

    if data:
        candidates = data.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                citation = candidate.get("citationMetadata")
                if isinstance(citation, dict):
                    citations = citation.get("citationSources")
                    if isinstance(citations, list):
                        for item in citations:
                            if not isinstance(item, dict):
                                continue
                            url = str(item.get("uri") or item.get("url") or "").strip()
                            title = str(item.get("title") or item.get("license") or "网页来源").strip()
                            _add_source_unique(sources, seen, _web_source(title, url))
                url_context = candidate.get("urlContextMetadata")
                if isinstance(url_context, dict):
                    url_items = url_context.get("urlMetadata")
                    if isinstance(url_items, list):
                        for item in url_items:
                            if not isinstance(item, dict):
                                continue
                            url = str(item.get("retrievedUrl") or item.get("url") or "").strip()
                            title = str(item.get("title") or item.get("urlRetrievalStatus") or "网页来源").strip()
                            _add_source_unique(sources, seen, _web_source(title, url))
    return sources


def _log_req(model: str, prompt: str) -> None:
    att_sizes = _log_attachment_image_sizes()
    _ai_log_req(
        "text-gemini-search",
        model,
        prompt,
        has_image=bool(att_sizes),
        image_sizes=att_sizes,
        provider="ofox",
    )


def _log_resp(model: str, *, success: bool, status_code: int | None, error_full: str = "") -> None:
    _ai_log_resp(
        "text-gemini-search",
        model,
        success=success,
        degraded=False,
        status_code=status_code,
        error_full=error_full,
        provider="ofox",
    )


def call_gemini_search_api(
    *,
    model: str,
    input_payload: str | list[dict],
    reasoning_mode: str | None = None,
    timeout: int = TEXT_TIMEOUT_SECONDS,
) -> dict:
    native_model = gemini_native_search_model_id(model)
    prompt = _input_to_prompt(input_payload)
    payload = _build_gemini_search_payload(input_payload, reasoning_mode=reasoning_mode)
    _log_req(native_model, prompt)
    try:
        resp = ofox.ofox_request(
            "POST",
            gemini_native_generate_content_endpoint(native_model),
            headers=ofox.ofox_gemini_headers(),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        err = repr(exc)
        _log_resp(native_model, success=False, status_code=None, error_full=err)
        raise HTTPException(status_code=504, detail=err) from exc
    except requests.exceptions.RequestException as exc:
        err = repr(exc)
        _log_resp(native_model, success=False, status_code=None, error_full=err)
        raise HTTPException(status_code=502, detail=err) from exc

    if resp.status_code != 200:
        err_body = ofox.extract_error_message_from_response(resp)
        raw_body = (resp.text or "")[:4000]
        err = f"HTTP {resp.status_code}; parsed={err_body!r}; body={raw_body!r}"
        _log_resp(native_model, success=False, status_code=resp.status_code, error_full=err)
        raise HTTPException(status_code=500, detail=err)

    data = resp.json()
    _log_resp(native_model, success=True, status_code=resp.status_code)
    return data


def parse_gemini_search_payload(data: dict) -> dict:
    grounding = _extract_grounding_metadata(data)
    return {
        "content": clean_response_text(_extract_candidate_text(data)),
        "sources": _extract_grounding_sources(grounding, data),
        "grounding": grounding,
        "raw": data,
    }


def stream_gemini_search_api(
    *,
    model: str,
    input_payload: str | list[dict],
    reasoning_mode: str | None = None,
    timeout: int = TEXT_TIMEOUT_SECONDS,
) -> Iterator[dict]:
    native_model = gemini_native_search_model_id(model)
    prompt = _input_to_prompt(input_payload)
    payload = _build_gemini_search_payload(input_payload, reasoning_mode=reasoning_mode)
    _log_req(native_model, prompt)
    try:
        resp = ofox.ofox_request(
            "POST",
            gemini_native_stream_generate_content_endpoint(native_model),
            headers=ofox.ofox_gemini_headers(),
            json=payload,
            timeout=timeout,
            stream=True,
        )
    except requests.exceptions.Timeout as exc:
        err = repr(exc)
        _log_resp(native_model, success=False, status_code=None, error_full=err)
        raise RuntimeError(err) from exc
    except requests.exceptions.RequestException as exc:
        err = repr(exc)
        _log_resp(native_model, success=False, status_code=None, error_full=err)
        raise RuntimeError(err) from exc

    if resp.status_code != 200:
        raw_body = (resp.text or "")[:4000]
        parsed = ofox.extract_error_message_from_response(resp)
        err = f"HTTP {resp.status_code}; parsed={parsed!r}; body={raw_body!r}"
        _log_resp(native_model, success=False, status_code=resp.status_code, error_full=err)
        raise RuntimeError(err)

    got_stop = False
    got_grounding = False
    final_data: dict | None = None
    last_event_data: dict | None = None
    full_text_parts: list[str] = []
    resp.encoding = "utf-8"
    for line in resp.iter_lines(decode_unicode=True):
        if line is None:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data:"):
            stripped = stripped[5:].strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        last_event_data = event

        text = _extract_candidate_text(event)
        if text:
            full_text_parts.append(text)
            yield {"type": "token", "text": text}

        candidates = event.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate0 = candidates[0] if isinstance(candidates[0], dict) else {}
            finish_reason = str(candidate0.get("finishReason") or "").strip().upper()
            grounding = candidate0.get("groundingMetadata")
            if finish_reason == "STOP":
                got_stop = True
            if isinstance(grounding, dict) and grounding:
                got_grounding = True
            if got_stop and got_grounding:
                final_data = event
                break

        err = event.get("error")
        if isinstance(err, dict):
            if got_stop and got_grounding:
                break
            raise RuntimeError(str(err.get("message") or err))

    if not final_data and got_stop:
        final_data = last_event_data if isinstance(last_event_data, dict) else {}

    if not final_data:
        _log_resp(
            native_model,
            success=False,
            status_code=resp.status_code,
            error_full="gemini stream completed without final grounding payload",
        )
        raise RuntimeError("gemini stream completed without final grounding payload")

    _log_resp(native_model, success=True, status_code=resp.status_code)
    parsed = parse_gemini_search_payload(final_data)
    if not (parsed.get("content") or "").strip():
        parsed["content"] = clean_response_text("".join(full_text_parts))
    yield {"type": "done", "payload": parsed}
