"""文本对话：消息组装与 /chat/completions。"""
from __future__ import annotations

import json
from typing import Any, Iterator, Optional

import requests
from fastapi import HTTPException

from app.ai_context import (
    _ai_log_req,
    _ai_log_resp,
    _last_user_text_for_log,
    _log_attachment_image_sizes,
    reset_ai_request_context,
    set_ai_request_context,
)
from app.config import DEFAULT_TEXT_SYSTEM_PROMPT, SUMMARY_MODEL, SUMMARY_TIMEOUT_SECONDS, TEXT_TIMEOUT_SECONDS
from app.models import ChatRequest, HistoryMessageItem, SummarizeHistoryRequest
from app.providers import ofox
from app.services.attachment_service import (
    clean_response_text,
    extract_text_from_content,
    extract_text_from_attachment_meta,
    read_attachment_meta_any,
    truncate_text,
)
from app.services.image_service import build_image_reference_data_urls
from app.services import (
    anthropic_text_service,
    model_capability_service,
    ofox_gemini_search_service,
    ofox_responses_service,
)


def history_item_to_text(item: HistoryMessageItem) -> str:
    parts = []

    text = (item.text or "").strip()
    if text:
        parts.append(text)

    if item.attachments:
        names = [att.name for att in item.attachments if att.name]
        if names:
            parts.append("该轮附带附件：" + "、".join(names))

    if item.has_image_result:
        parts.append("该轮回复里包含一张已生成图片。")

    joined = "\n".join(parts).strip()
    return joined or "[空白消息]"


def format_history_transcript(history_messages: list[HistoryMessageItem]) -> str:
    lines = []
    for item in history_messages:
        role = "用户" if item.role == "user" else "助手"
        lines.append(f"{role}：{history_item_to_text(item)}")
    return "\n\n".join(lines).strip()


def resolve_chat_system_prompt(system_prompt: Optional[str]) -> str:
    if system_prompt is None:
        return DEFAULT_TEXT_SYSTEM_PROMPT
    return (system_prompt or "").strip()


def build_contextual_prompt(
    prompt: str,
    summary: str,
    history_messages: list[HistoryMessageItem],
    attachment_context: str,
) -> str:
    sections = []

    if summary.strip():
        sections.append("会话长期摘要：\n" + summary.strip())

    history_text = format_history_transcript(history_messages[-20:])
    if history_text:
        sections.append("最近对话：\n" + history_text)

    sections.append("当前用户要求：\n" + prompt.strip())

    if attachment_context:
        sections.append("当前上传附件信息：\n" + attachment_context)

    return "\n\n".join(section for section in sections if section).strip()


def build_text_attachment_context(attachment_ids: list[str]) -> str:
    if not attachment_ids:
        return ""

    docs = []
    notes = []

    for attachment_id in attachment_ids:
        meta = read_attachment_meta_any(attachment_id)
        if not meta:
            continue

        if meta.get("category") == "image":
            continue

        name = meta.get("original_name") or "未命名文件"
        extracted = truncate_text(extract_text_from_attachment_meta(meta), 12000)
        if extracted:
            docs.append(f"文件名：{name}\n文件内容如下：\n{extracted}")
        else:
            notes.append(f"{name} 已上传，但暂未解析出可用文本内容。")

    sections = []
    if docs:
        sections.append("以下是当前上传的文件内容：\n\n" + "\n\n===== 分隔 =====\n\n".join(docs))
    if notes:
        sections.append("附件说明：" + "；".join(notes))
    return "\n\n".join(sections).strip()


def build_current_user_message_content(
    prompt: str,
    attachment_ids: list[str] | None = None,
) -> str | list[dict]:
    att_ids = attachment_ids or []
    text_sections = [(prompt or "").strip()]
    attachment_context = build_text_attachment_context(att_ids)
    if attachment_context:
        text_sections.append(attachment_context)
    text_content = "\n\n".join(section for section in text_sections if section).strip()

    content_parts = []
    if text_content:
        content_parts.append({"type": "text", "text": text_content})

    for image_data_url in build_image_reference_data_urls(att_ids):
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {"url": image_data_url},
            }
        )

    if not content_parts:
        return ""
    if len(content_parts) == 1 and content_parts[0].get("type") == "text":
        return text_content
    return content_parts


def build_text_chat_messages(
    system_prompt: str,
    summary: str,
    history_messages: list[HistoryMessageItem],
    current_user_content: str | list[dict],
    knowledge_context: str = "",
    web_search_context: str = "",
) -> list[dict]:
    messages = []
    if (system_prompt or "").strip():
        messages.append(
            {
                "role": "system",
                "content": system_prompt.strip(),
            }
        )

    if knowledge_context.strip():
        messages.append({
            "role": "system",
            "content": (
                "下面是从企业知识库检索到的参考资料。"
                "请只在与用户当前问题相关时使用。"
                "如果资料不足或不确定，请明确说明，不要编造。\n\n"
                f"{knowledge_context.strip()}"
            )
        })

    if web_search_context.strip():
        messages.append({
            "role": "system",
            "content": (
                "下面是联网搜索到的公开网页摘要。"
                "请只在与用户当前问题相关时使用。"
                "如果搜索结果不足或不确定，请明确说明，不要编造。\n\n"
                f"{web_search_context.strip()}"
            )
        })

    if summary.strip():
        messages.append({
            "role": "system",
            "content": (
                "下面是当前会话较早历史压缩后的长期摘要。"
                "请把它当作已确认背景，仅在相关时使用，不要逐字复述：\n\n"
                f"{summary.strip()}"
            )
        })

    for item in history_messages[-20:]:
        role = "assistant" if item.role == "assistant" else "user"
        messages.append({
            "role": "assistant" if role == "assistant" else "user",
            "content": history_item_to_text(item)
        })

    messages.append({
        "role": "user",
        "content": current_user_content
    })

    return messages


def merge_response_notes(*notes: str) -> str:
    merged: list[str] = []
    for note in notes:
        text = (note or "").strip()
        if text:
            merged.append(text)
    return "\n".join(merged)


def supports_builtin_web_search(model: str) -> bool:
    return ofox_responses_service.supports_builtin_web_search(model)


def supports_gemini_builtin_web_search(model: str) -> bool:
    return ofox_gemini_search_service.supports_gemini_builtin_web_search(model)


def web_search_fallback_note(model: str) -> str:
    normalized = (model or "").strip().lower()
    if normalized == "anthropic/claude-opus-4.7":
        return "Claude Opus 4.7 当前不支持 OFOX 内建联网搜索，已按普通对话回答"
    return "当前模型暂不支持内建联网搜索，已按普通对话回答"


def build_effective_request_meta(model: str, reasoning_mode: str | None) -> dict[str, Any]:
    adapter = model_capability_service.build_text_request_adapter(model, reasoning_mode)
    return {
        "effective_model": str(model or "").strip(),
        "effective_upstream_model": str(adapter.get("effective_model") or model or "").strip(),
        "effective_reasoning_mode": str(
            adapter.get("effective_reasoning_mode")
            or model_capability_service.REASONING_MODE_DEFAULT
        ),
        "effective_provider": str(adapter.get("provider") or "unknown"),
        "effective_transport": str(adapter.get("transport") or "ofox_openai_compat"),
    }


def call_chat_completion(
    model: str,
    messages: list[dict],
    reasoning_mode: str | None = None,
    temperature: float = 0.7,
    timeout: int = TEXT_TIMEOUT_SECONDS,
) -> str:
    adapter = model_capability_service.build_text_request_adapter(model, reasoning_mode)
    effective_model = str(adapter.get("effective_model") or model or "").strip()
    provider_label = (
        "ofox-anthropic"
        if str(adapter.get("transport") or "") == "ofox_anthropic_native"
        else "ofox"
    )
    prompt_preview = _last_user_text_for_log(messages)
    att_sizes = _log_attachment_image_sizes()
    _ai_log_req(
        "text",
        effective_model,
        prompt_preview,
        has_image=bool(att_sizes),
        image_sizes=att_sizes,
        provider=provider_label,
    )

    if str(adapter.get("transport") or "") == "ofox_anthropic_native":
        try:
            text = anthropic_text_service.call_anthropic_messages_api(
                model=effective_model,
                messages=messages,
                temperature=temperature,
                timeout=timeout,
                anthropic_extra=adapter.get("anthropic_extra") or {},
            )
        except HTTPException as exc:
            _ai_log_resp(
                "text",
                effective_model,
                success=False,
                degraded=False,
                status_code=exc.status_code,
                error_full=str(exc.detail),
                provider=provider_label,
            )
            raise
        _ai_log_resp(
            "text",
            effective_model,
            success=True,
            degraded=False,
            status_code=200,
            error_full="",
            provider=provider_label,
        )
        return text

    payload = {
        "model": effective_model,
        "messages": messages,
        "temperature": temperature,
    }
    payload.update(adapter.get("chat_completions_extra") or {})

    try:
        resp = ofox.ofox_request(
            "POST",
            ofox.ofox_chat_completions_url(),
            headers=ofox.ofox_json_headers(),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        err = repr(e)
        _ai_log_resp(
            "text",
            effective_model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider=provider_label,
        )
        raise HTTPException(status_code=504, detail=err) from e
    except requests.exceptions.RequestException as e:
        err = repr(e)
        _ai_log_resp(
            "text",
            effective_model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider=provider_label,
        )
        raise HTTPException(status_code=502, detail=err) from e

    if resp.status_code != 200:
        err_body = ofox.extract_error_message_from_response(resp)
        try:
            raw_body = (resp.text or "")[:4000]
        except Exception:
            raw_body = ""
        err = f"HTTP {resp.status_code}; parsed={err_body!r}; body={raw_body!r}"
        _ai_log_resp(
            "text",
            effective_model,
            success=False,
            degraded=False,
            status_code=resp.status_code,
            error_full=err,
            provider=provider_label,
        )
        raise HTTPException(status_code=500, detail=err)

    data = resp.json()
    message = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
    raw_content = message.get("content")
    _ai_log_resp(
        "text",
        effective_model,
        success=True,
        degraded=False,
        status_code=resp.status_code,
        error_full="",
        provider=provider_label,
    )
    return clean_response_text(extract_text_from_content(raw_content))


def stream_chat_completion(
    model: str,
    messages: list[dict],
    reasoning_mode: str | None = None,
    temperature: float = 0.7,
    timeout: int = TEXT_TIMEOUT_SECONDS,
) -> Iterator[str | dict]:
    """流式文本：逐块 yield 文本片段；若上游返回推理字段则透传为事件。"""
    adapter = model_capability_service.build_text_request_adapter(model, reasoning_mode)
    effective_model = str(adapter.get("effective_model") or model or "").strip()
    provider_label = (
        "ofox-anthropic"
        if str(adapter.get("transport") or "") == "ofox_anthropic_native"
        else "ofox"
    )
    prompt_preview = _last_user_text_for_log(messages)
    att_sizes = _log_attachment_image_sizes()
    _ai_log_req(
        "text",
        effective_model,
        prompt_preview,
        has_image=bool(att_sizes),
        image_sizes=att_sizes,
        provider=provider_label,
    )

    if str(adapter.get("transport") or "") == "ofox_anthropic_native":
        try:
            for chunk in anthropic_text_service.stream_anthropic_messages_api(
                model=effective_model,
                messages=messages,
                temperature=temperature,
                timeout=timeout,
                anthropic_extra=adapter.get("anthropic_extra") or {},
            ):
                yield chunk
        except Exception as exc:
            _ai_log_resp(
                "text",
                effective_model,
                success=False,
                degraded=False,
                status_code=None,
                error_full=str(exc),
                provider=provider_label,
            )
            raise
        _ai_log_resp(
            "text",
            effective_model,
            success=True,
            degraded=False,
            status_code=200,
            error_full="",
            provider=provider_label,
        )
        return

    payload = {
        "model": effective_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    payload.update(adapter.get("chat_completions_extra") or {})

    try:
        resp = ofox.ofox_request(
            "POST",
            ofox.ofox_chat_completions_url(),
            headers=ofox.ofox_json_headers(),
            json=payload,
            timeout=timeout,
            stream=True,
        )
    except requests.exceptions.Timeout as e:
        err = repr(e)
        _ai_log_resp(
            "text",
            effective_model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider=provider_label,
        )
        raise RuntimeError(err) from e
    except requests.exceptions.RequestException as e:
        err = repr(e)
        _ai_log_resp(
            "text",
            effective_model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider=provider_label,
        )
        raise RuntimeError(err) from e

    if resp.status_code != 200:
        try:
            raw_body = (resp.text or "")[:4000]
        except Exception:
            raw_body = ""
        parsed = ofox.extract_error_message_from_response(resp)
        err = f"HTTP {resp.status_code}; parsed={parsed!r}; body={raw_body!r}"
        _ai_log_resp(
            "text",
            effective_model,
            success=False,
            degraded=False,
            status_code=resp.status_code,
            error_full=err,
            provider=provider_label,
        )
        raise RuntimeError(err)

    resp.encoding = "utf-8"
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            reasoning_text = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
                or delta.get("thinking")
            )
            if reasoning_text:
                yield {"type": "reasoning", "text": str(reasoning_text)}
            text = delta.get("content")
            if text:
                yield text
        except (json.JSONDecodeError, IndexError, KeyError):
            continue

    _ai_log_resp(
        "text",
        effective_model,
        success=True,
        degraded=False,
        status_code=resp.status_code,
        error_full="",
        provider=provider_label,
    )


def perform_chat(
    req: ChatRequest,
    *,
    knowledge_context: str = "",
    web_search_context: str = "",
    response_note: str = "",
    response_sources: list[dict] | None = None,
    rag_status: str = "",
) -> dict:
    """POST /api/chat 业务体：返回 {"content": str}。"""
    adapter = model_capability_service.build_text_request_adapter(req.model, req.reasoning_mode)
    meta = build_effective_request_meta(req.model, req.reasoning_mode)
    current_user_content = build_current_user_message_content(
        req.prompt,
        req.attachment_ids,
    )

    messages = build_text_chat_messages(
        system_prompt=resolve_chat_system_prompt(req.system_prompt),
        summary=req.summary or "",
        history_messages=req.history_messages or [],
        current_user_content=current_user_content,
        knowledge_context=knowledge_context,
        web_search_context=web_search_context,
    )

    if req.use_web_search and supports_builtin_web_search(req.model):
        try:
            parsed = ofox_responses_service.parse_responses_web_search_payload(
                ofox_responses_service.call_responses_api(
                    model=req.model,
                    input_payload=messages,
                    tools=ofox_responses_service.build_responses_web_search_tool(),
                    reasoning_effort=str(
                        (adapter.get("chat_completions_extra") or {}).get("reasoning_effort") or ""
                    ) or None,
                    timeout=TEXT_TIMEOUT_SECONDS,
                )
            )
            return {
                "content": parsed.get("content") or "模型没有返回可显示内容。",
                "note": merge_response_notes(response_note, "已使用模型内建联网搜索"),
                "sources": [*(response_sources or []), *(parsed.get("sources") or [])],
                "rag_status": rag_status or "",
                **meta,
            }
        except Exception:
            response_note = merge_response_notes(
                response_note,
                "模型内建联网搜索暂不可用，已按普通对话回答",
            )
    elif req.use_web_search and supports_gemini_builtin_web_search(req.model):
        try:
            parsed = ofox_gemini_search_service.parse_gemini_search_payload(
                ofox_gemini_search_service.call_gemini_search_api(
                    model=req.model,
                    input_payload=messages,
                    reasoning_mode=req.reasoning_mode,
                    timeout=TEXT_TIMEOUT_SECONDS,
                )
            )
            return {
                "content": parsed.get("content") or "模型没有返回可显示内容。",
                "note": merge_response_notes(response_note, "已使用模型内建联网搜索"),
                "sources": [*(response_sources or []), *(parsed.get("sources") or [])],
                "rag_status": rag_status or "",
                **meta,
            }
        except Exception:
            response_note = merge_response_notes(
                response_note,
                "模型内建联网搜索暂不可用，已按普通对话回答",
            )
    elif req.use_web_search:
        response_note = merge_response_notes(
            response_note,
            web_search_fallback_note(req.model),
        )

    content = call_chat_completion(
        model=req.model,
        messages=messages,
        reasoning_mode=req.reasoning_mode,
        temperature=0.7,
        timeout=TEXT_TIMEOUT_SECONDS,
    )

    return {
        "content": content,
        "note": response_note or "",
        "sources": response_sources or [],
        "rag_status": rag_status or "",
        **meta,
    }


def perform_summarize_history(req: SummarizeHistoryRequest) -> dict:
    """POST /api/summarize-history：调用方已做 auth；内部管理 ai_context。"""
    if not req.history_messages:
        return {"summary": req.current_summary or ""}

    rid_t, att_t, im_t = set_ai_request_context([], None)
    try:
        transcript = format_history_transcript(req.history_messages)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是会话记忆整理器。"
                    "你的任务是把一段较早历史压缩成供后续对话调用的长期摘要。"
                    "不要寒暄，不要写分析过程，不要分角色复述整段聊天。"
                )
            },
            {
                "role": "user",
                "content": (
                    "请把【已有摘要】和【新增历史】合并成一版新的长期记忆摘要。\n\n"
                    "要求：\n"
                    "1. 只保留后续继续对话真正有用的信息\n"
                    "2. 包括：目标、已确认要求、风格偏好、模型/模式偏好、已上传文件与用途、关键结论、未完成事项\n"
                    "3. 用简体中文\n"
                    "4. 不要写客套话，不要重复\n"
                    "5. 控制在 200 到 400 字左右\n\n"
                    f"【已有摘要】\n{req.current_summary or '无'}\n\n"
                    f"【新增历史】\n{transcript}"
                )
            }
        ]

        summary = call_chat_completion(
            model=SUMMARY_MODEL,
            messages=messages,
            reasoning_mode=None,
            temperature=0.2,
            timeout=SUMMARY_TIMEOUT_SECONDS,
        )
        return {"summary": summary}
    finally:
        reset_ai_request_context(rid_t, att_t, im_t)
