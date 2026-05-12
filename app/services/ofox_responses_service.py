"""OFOX Responses API：内建 web_search 调用、流式解析与结果归一化。"""
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
from app.config import RESPONSES_MAX_OUTPUT_TOKENS, TEXT_TIMEOUT_SECONDS
from app.providers import ofox
from app.services.attachment_service import clean_response_text, extract_text_from_content


def supports_builtin_web_search(model: str) -> bool:
    return (model or "").strip().lower().startswith("openai/gpt-")


def build_responses_web_search_tool() -> list[dict]:
    return [{"type": "web_search"}]


def _build_responses_payload(
    *,
    model: str,
    input_payload: str | list[dict],
    tools: list[dict] | None = None,
    reasoning_effort: str | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": input_payload,
        "max_output_tokens": RESPONSES_MAX_OUTPUT_TOKENS,
    }
    if tools:
        payload["tools"] = tools
        if any(isinstance(tool, dict) and tool.get("type") == "web_search" for tool in tools):
            payload["include"] = ["web_search_call.action.sources"]
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    if stream:
        payload["stream"] = True
    return payload


def call_responses_api(
    *,
    model: str,
    input_payload: str | list[dict],
    tools: list[dict] | None = None,
    reasoning_effort: str | None = None,
    timeout: int = TEXT_TIMEOUT_SECONDS,
) -> dict:
    prompt_preview = (
        _last_user_text_for_log(input_payload)
        if isinstance(input_payload, list)
        else str(input_payload or "")
    )
    att_sizes = _log_attachment_image_sizes()
    _ai_log_req(
        "text-responses",
        model,
        prompt_preview,
        has_image=bool(att_sizes),
        image_sizes=att_sizes,
        provider="ofox",
    )

    payload = _build_responses_payload(
        model=model,
        input_payload=input_payload,
        tools=tools,
        reasoning_effort=reasoning_effort,
        stream=False,
    )

    try:
        resp = ofox.ofox_request(
            "POST",
            ofox.ofox_responses_url(),
            headers=ofox.ofox_json_headers(),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        err = repr(exc)
        _ai_log_resp(
            "text-responses",
            model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise HTTPException(status_code=504, detail=err) from exc
    except requests.exceptions.RequestException as exc:
        err = repr(exc)
        _ai_log_resp(
            "text-responses",
            model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise HTTPException(status_code=502, detail=err) from exc

    if resp.status_code != 200:
        err_body = ofox.extract_error_message_from_response(resp)
        try:
            raw_body = (resp.text or "")[:4000]
        except Exception:
            raw_body = ""
        err = f"HTTP {resp.status_code}; parsed={err_body!r}; body={raw_body!r}"
        _ai_log_resp(
            "text-responses",
            model,
            success=False,
            degraded=False,
            status_code=resp.status_code,
            error_full=err,
            provider="ofox",
        )
        raise HTTPException(status_code=500, detail=err)

    data = resp.json()
    _ai_log_resp(
        "text-responses",
        model,
        success=True,
        degraded=False,
        status_code=resp.status_code,
        error_full="",
        provider="ofox",
    )
    return data


def stream_responses_api(
    *,
    model: str,
    input_payload: str | list[dict],
    tools: list[dict] | None = None,
    reasoning_effort: str | None = None,
    timeout: int = TEXT_TIMEOUT_SECONDS,
) -> Iterator[dict]:
    prompt_preview = (
        _last_user_text_for_log(input_payload)
        if isinstance(input_payload, list)
        else str(input_payload or "")
    )
    att_sizes = _log_attachment_image_sizes()
    _ai_log_req(
        "text-responses",
        model,
        prompt_preview,
        has_image=bool(att_sizes),
        image_sizes=att_sizes,
        provider="ofox",
    )

    payload = _build_responses_payload(
        model=model,
        input_payload=input_payload,
        tools=tools,
        reasoning_effort=reasoning_effort,
        stream=True,
    )

    try:
        resp = ofox.ofox_request(
            "POST",
            ofox.ofox_responses_url(),
            headers=ofox.ofox_json_headers(),
            json=payload,
            timeout=timeout,
            stream=True,
        )
    except requests.exceptions.Timeout as exc:
        err = repr(exc)
        _ai_log_resp(
            "text-responses",
            model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err) from exc
    except requests.exceptions.RequestException as exc:
        err = repr(exc)
        _ai_log_resp(
            "text-responses",
            model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err) from exc

    if resp.status_code != 200:
        try:
            raw_body = (resp.text or "")[:4000]
        except Exception:
            raw_body = ""
        parsed = ofox.extract_error_message_from_response(resp)
        err = f"HTTP {resp.status_code}; parsed={parsed!r}; body={raw_body!r}"
        _ai_log_resp(
            "text-responses",
            model,
            success=False,
            degraded=False,
            status_code=resp.status_code,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err)

    last_event: str = ""
    completed_response: dict | None = None
    resp.encoding = "utf-8"
    for line in resp.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if not line:
            continue
        if line.startswith("event:"):
            last_event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if not data_str:
            continue
        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        event_type = str(event.get("type") or last_event or "").strip()
        if event_type.startswith("response.web_search_call."):
            if event_type.endswith(".in_progress"):
                yield {"type": "search", "text": "正在启动网页搜索"}
            elif event_type.endswith(".searching"):
                yield {"type": "search", "text": "正在搜索网页"}
            elif event_type.endswith(".completed"):
                yield {"type": "search", "text": "网页搜索完成，正在整理结果"}
            continue

        if event_type in {"response.output_item.added", "response.output_item.done"}:
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            item_type = str(item.get("type") or "").strip()
            if item_type == "web_search_call":
                action = item.get("action") if isinstance(item.get("action"), dict) else {}
                query = str(action.get("query") or action.get("search_query") or "").strip()
                sources = _sources_from_any(item)
                if query:
                    yield {"type": "search", "text": f"正在搜索：{query}"}
                if sources:
                    yield {"type": "sources", "sources": sources}
                continue

        if "reasoning" in event_type:
            reasoning_text = _extract_reasoning_event_text(event)
            if reasoning_text:
                yield {"type": "reasoning", "text": reasoning_text}
            continue

        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                yield {"type": "token", "text": delta}
            continue

        if event_type == "response.completed":
            completed_response = event.get("response") if isinstance(event.get("response"), dict) else None
            break

        if event_type == "response.failed":
            error_obj = event.get("response", {}).get("error") if isinstance(event.get("response"), dict) else event.get("error")
            raise RuntimeError(str(error_obj or "responses stream failed"))

    final_data = completed_response or {}
    _ai_log_resp(
        "text-responses",
        model,
        success=bool(final_data),
        degraded=False,
        status_code=resp.status_code,
        error_full="" if final_data else "responses stream completed without response.completed",
        provider="ofox",
    )
    if not final_data:
        raise RuntimeError("responses stream completed without response.completed")
    yield {
        "type": "done",
        "payload": parse_responses_web_search_payload(final_data),
    }


def extract_responses_output_text(data: dict) -> str:
    outputs = data.get("output")
    if not isinstance(outputs, list):
        return ""

    parts: list[str] = []
    for item in outputs:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue
        content = item.get("content")
        extracted = extract_text_from_content(content)
        if extracted:
            parts.append(extracted)
    return clean_response_text("\n".join(part for part in parts if part).strip())


def _derive_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or ""
    except Exception:
        return ""


def _snippet_from_annotation(text: str, ann: dict) -> str:
    start = ann.get("start_index")
    end = ann.get("end_index")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
        snippet = text[max(0, start - 90):min(len(text), end + 90)].strip()
        if snippet:
            return snippet
    return text[:240].strip()


def _source_from_raw(raw: dict, *, fallback_title: str = "网页来源") -> dict | None:
    url = str(
        raw.get("url")
        or raw.get("uri")
        or raw.get("link")
        or raw.get("href")
        or ""
    ).strip()
    title = str(
        raw.get("title")
        or raw.get("name")
        or raw.get("page_title")
        or fallback_title
    ).strip() or fallback_title
    if not url and not title:
        return None
    domain = _derive_domain(url)
    snippet = str(raw.get("snippet") or raw.get("summary") or raw.get("text") or "").strip()
    return {
        "source_type": "web",
        "title": title,
        "snippet": snippet,
        "url": url,
        "domain": domain,
        "published_at": str(raw.get("published_at") or raw.get("date") or "").strip(),
        "meta_label": domain,
    }


def _sources_from_any(value: Any) -> list[dict]:
    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(src: dict | None) -> None:
        if not src:
            return
        key = (str(src.get("title") or ""), str(src.get("url") or ""))
        if key in seen:
            return
        seen.add(key)
        sources.append(src)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_type = str(node.get("type") or "").strip()
            if node_type in {"url_citation", "source", "web_source"} or any(k in node for k in ("url", "uri", "link", "href")):
                add(_source_from_raw(node))
            raw_sources = node.get("sources")
            if isinstance(raw_sources, list):
                for item in raw_sources:
                    if isinstance(item, dict):
                        add(_source_from_raw(item))
                    else:
                        walk(item)
            for key, child in node.items():
                if key == "sources":
                    continue
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sources


def _extract_reasoning_event_text(event: dict) -> str:
    for key in ("delta", "text", "summary_text", "content"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    part = event.get("part")
    if isinstance(part, dict):
        for key in ("text", "summary_text", "content"):
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    item = event.get("item")
    if isinstance(item, dict):
        for key in ("text", "summary_text", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def extract_web_search_sources(data: dict) -> list[dict]:
    outputs = data.get("output")
    if not isinstance(outputs, list):
        return []

    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for src in _sources_from_any(data):
        key = (str(src.get("title") or ""), str(src.get("url") or ""))
        if key in seen:
            continue
        seen.add(key)
        sources.append(src)

    for item in outputs:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text") or "").strip()
            annotations = block.get("annotations")
            if not isinstance(annotations, list):
                continue
            for ann in annotations:
                if not isinstance(ann, dict):
                    continue
                if ann.get("type") != "url_citation":
                    continue
                url = str(ann.get("url") or "").strip()
                title = str(ann.get("title") or "网页来源").strip() or "网页来源"
                domain = _derive_domain(url)
                snippet = _snippet_from_annotation(text, ann)
                dedupe_key = (title, url)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                sources.append(
                    {
                        "source_type": "web",
                        "title": title,
                        "snippet": snippet,
                        "url": url,
                        "domain": domain,
                        "published_at": "",
                        "meta_label": domain,
                    }
                )
    return sources


def parse_responses_web_search_payload(data: dict) -> dict:
    return {
        "content": extract_responses_output_text(data),
        "sources": extract_web_search_sources(data),
        "raw": data,
    }
