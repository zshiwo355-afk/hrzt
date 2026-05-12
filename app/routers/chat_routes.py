"""文本对话与摘要。"""
from __future__ import annotations

import asyncio
import json
import queue
import re
import threading
import time

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.ai_context import (
    _ai_image_mode_var,
    _ai_log_attachment_ids_var,
    _ai_request_id_var,
    get_ai_request_id,
    reset_ai_request_context,
    set_ai_request_context,
)
from app.config import TEXT_TIMEOUT_SECONDS, WS_KEEPALIVE_SECONDS
from app.logging_config import logger
from app.models import ChatRequest, SummarizeHistoryRequest
from app.auth import require_auth
from app.db import get_db, get_session_factory
from app.services.attachment_service import clean_response_text
from app.services import (
    auth_service,
    chat_service,
    conversation_service,
    message_service,
    model_capability_service,
    model_service,
    ofox_gemini_search_service,
    ofox_responses_service,
    rag_service,
)

router = APIRouter(tags=["chat"])

PROCESS_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?:[-*]\s*)?"
    r"(?:\*\*|__)?"
    r"(?:"
    r"Analy[sz]ing|Exploring|Retrieving|Fetching|Searching|Investigating|Validating|Checking|"
    r"Reviewing|Recalling|Interpreting|Identifying|Processing|Gathering|Reading|Scanning|Looking\s+up|"
    r"Preparing|Understanding|Planning|Thinking|Reasoning|Finding|Discovering|Recommending|"
    r"Selecting|Curating|Comparing|Ranking|Evaluating|Assessing|Examining|Sifting|Shortlisting"
    r")\b.*$",
    flags=re.IGNORECASE,
)
PROCESS_SENTENCE_RE = re.compile(
    r"^\s*(?:This is your|This week|I'?m|I am|I'?ve|I have|I will|I'll|Let me|"
    r"Now I(?:'m| am)|My focus is|My focus has|My aim is|This suggests|I need to|We're|We are|These include)\b.*"
    r"(?:search|process|analy[sz]|fetch|dig|investigat|validat|check|look|"
    r"identify|identified|focus|drill|understand|provide|bypass|adapt|organize|gather|retriev|review|reviewing|recall|recalling|pinpoint|articulat|"
    r"checking|trending|repositories|infrastructure|rewrite|movement|leading|projects|innovative|"
    r"discussions|illustrat|include|pushing|embodied|shifted|dissecting|developments|surrounding|tensions|talks)",
    flags=re.IGNORECASE,
)
LIKELY_ANSWER_START_RE = re.compile(r"^\s*(?:[\u4e00-\u9fff]|#{1,6}\s*[\u4e00-\u9fff]|[-*]\s*[\u4e00-\u9fff]|\d+[.)、]\s*[\u4e00-\u9fff])")


def _strip_leading_process_narration(text: str) -> str:
    """Remove model-generated process narration before it reaches the UI."""
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    skip_head = True
    skip_process_paragraph = False
    skipped_blocks = 0
    for line in lines:
        stripped = line.strip()
        if skip_head:
            if skip_process_paragraph:
                if not stripped:
                    skip_process_paragraph = False
                elif LIKELY_ANSWER_START_RE.match(stripped):
                    out.append(line)
                    skip_head = False
                    skip_process_paragraph = False
                continue
            if not stripped:
                continue
            if PROCESS_HEADING_RE.match(stripped):
                skip_process_paragraph = True
                skipped_blocks += 1
                continue
            if skipped_blocks and PROCESS_SENTENCE_RE.match(stripped):
                continue
            if not skipped_blocks and PROCESS_SENTENCE_RE.match(stripped):
                skipped_blocks += 1
                continue
        out.append(line)
        if stripped:
            skip_head = False
    return "\n".join(out).lstrip()


def _build_rag_bundle_safe(req: ChatRequest) -> dict:
    try:
        return rag_service.build_rag_bundle(req)
    except Exception as exc:
        logger.warning(
            "[rag-bundle-fallback] conversation_id=%s use_rag=%s error=%r",
            req.conversation_id,
            req.use_rag,
            exc,
        )
        return {
            "used": False,
            "query": (req.rag_query or req.prompt or "").strip(),
            "sources": [],
            "context_text": "",
            "note": "知识库服务暂不可用",
            "rag_status": "error",
        }


def _merge_response_notes(*notes: str) -> str:
    merged: list[str] = []
    for note in notes:
        text = (note or "").strip()
        if text:
            merged.append(text)
    return "\n".join(merged)


def _merge_response_sources(rag_sources: list[dict], web_sources: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for row in rag_sources or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["source_type"] = "rag"
        merged.append(item)
    for row in web_sources or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item["source_type"] = "web"
        merged.append(item)
    return merged


@router.post("/api/summarize-history")
def summarize_history(req: SummarizeHistoryRequest, request: Request):
    require_auth(request)
    try:
        return chat_service.perform_summarize_history(req)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"会话摘要失败：{repr(e)}") from e


def _prepare_db_chat_context(db: Session, request: Request, req: ChatRequest):
    user_id = require_auth(request)
    model_service.ensure_model_allowed(req.model, mode="text")
    user = auth_service.get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="请先登录。")

    conversation = conversation_service.get_conversation_for_user(db, req.conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或无权限。")

    attachments = message_service.build_attachment_snapshots(req.attachment_ids or [])
    user_text = (req.prompt or "").strip()
    message_service.create_user_message(
        db,
        conversation_id=conversation.id,
        user_id=user.id,
        content=user_text,
        model=req.model,
        attachments=attachments,
    )
    assistant_message = message_service.create_assistant_placeholder(
        db,
        conversation_id=conversation.id,
        user_id=user.id,
        model=req.model,
    )
    conversation_service.maybe_set_first_title(db, conversation, user_text)
    conversation_service.touch_conversation(
        db,
        conversation,
        model=req.model,
        last_message_at=datetime.now(),
    )
    return user, conversation, assistant_message


@router.post("/api/chat")
def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    _, conversation, assistant_message = _prepare_db_chat_context(db, request, req)
    rag_bundle = _build_rag_bundle_safe(req)
    merged_sources = _merge_response_sources(rag_bundle.get("sources") or [], [])
    merged_note = _merge_response_notes(rag_bundle.get("note") or "")
    stream_note = merged_note
    if req.use_web_search and not (
        chat_service.supports_builtin_web_search(req.model)
        or chat_service.supports_gemini_builtin_web_search(req.model)
    ):
        stream_note = chat_service.merge_response_notes(
            merged_note,
            chat_service.web_search_fallback_note(req.model),
        )

    rid_t, att_t, im_t = set_ai_request_context(req.attachment_ids or [], None)
    try:
        effective_meta = chat_service.build_effective_request_meta(req.model, req.reasoning_mode)
        payload = chat_service.perform_chat(
            req,
            knowledge_context=rag_bundle.get("context_text") or "",
            response_note=merged_note,
            response_sources=merged_sources,
            rag_status=rag_bundle.get("rag_status") or "",
        )
        message_service.complete_assistant_message(
            db,
            message_id=assistant_message.id,
            content=payload.get("content") or "",
        )
        payload["message_id"] = assistant_message.id
        payload.update(effective_meta)
        conversation_service.touch_conversation(
            db,
            conversation,
            model=req.model,
            last_message_at=datetime.now(),
        )
        return payload
    except HTTPException:
        message_service.fail_assistant_message(
            db,
            message_id=assistant_message.id,
            error_message="上游接口返回错误。",
        )
        raise
    except Exception as e:
        message_service.fail_assistant_message(
            db,
            message_id=assistant_message.id,
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        reset_ai_request_context(rid_t, att_t, im_t)


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    """流式文本对话（SSE），走标准 HTTP，反代兼容性通常好于 WebSocket。"""
    _, conversation, assistant_message = _prepare_db_chat_context(db, request, req)

    rag_bundle = _build_rag_bundle_safe(req)
    merged_sources = _merge_response_sources(rag_bundle.get("sources") or [], [])
    merged_note = _merge_response_notes(rag_bundle.get("note") or "")
    stream_note = merged_note
    if req.use_web_search and not (
        chat_service.supports_builtin_web_search(req.model)
        or chat_service.supports_gemini_builtin_web_search(req.model)
    ):
        stream_note = chat_service.merge_response_notes(
            merged_note,
            chat_service.web_search_fallback_note(req.model),
        )

    messages = chat_service.build_text_chat_messages(
        system_prompt=chat_service.resolve_chat_system_prompt(req.system_prompt),
        summary=req.summary or "",
        history_messages=req.history_messages or [],
        current_user_content=chat_service.build_current_user_message_content(
            req.prompt,
            req.attachment_ids,
        ),
        knowledge_context=rag_bundle.get("context_text") or "",
    )
    effective_meta = chat_service.build_effective_request_meta(req.model, req.reasoning_mode)
    effective_adapter = model_capability_service.build_text_request_adapter(
        req.model,
        req.reasoning_mode,
    )

    chunk_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()
    att_list = req.attachment_ids or []

    async def event_gen():
        # ContextVar 的 set/reset 必须发生在同一 asyncio 上下文中；StreamingResponse 在独立消费路径里结束生成器，
        # 若在路由外层 set、在 event_gen.finally 里 reset，会触发「Token was created in a different Context」。
        rid_t, att_t, im_t = set_ai_request_context(req.attachment_ids or [], None)
        bound_rid = get_ai_request_id()

        def _run_stream():
            _ai_request_id_var.set(bound_rid)
            _ai_log_attachment_ids_var.set(att_list)
            _ai_image_mode_var.set("")
            last_progress_sig = {"value": ""}
            answer_started = {"value": False}
            full_text_for_db: list[str] = []
            final_content_for_db = {"value": ""}
            def _progress(kind: str, text: str, **extra):
                if stop_event.is_set():
                    return
                sig = f"{kind}|{text}"
                if last_progress_sig["value"] == sig:
                    return
                last_progress_sig["value"] = sig
                payload = {"kind": kind, "text": text}
                payload.update(extra)
                chunk_queue.put(("progress", payload))

            try:
                if (rag_bundle.get("rag_status") or "") == "hit":
                    _progress("search", "已命中知识库内容，正在整理上下文")
                elif rag_bundle.get("rag_status"):
                    _progress("status", rag_bundle.get("note") or "知识库检索完成")

                if req.use_web_search and chat_service.supports_builtin_web_search(req.model):
                    try:
                        _progress("search", "正在调用模型内建联网搜索")
                        for event in ofox_responses_service.stream_responses_api(
                            model=req.model,
                            input_payload=messages,
                            tools=ofox_responses_service.build_responses_web_search_tool(),
                            reasoning_effort=str(
                                (effective_adapter.get("chat_completions_extra") or {}).get("reasoning_effort") or ""
                            ) or None,
                            timeout=TEXT_TIMEOUT_SECONDS,
                        ):
                            if stop_event.is_set():
                                break
                            if event.get("type") == "token":
                                if not answer_started["value"]:
                                    _progress("reasoning", "已获得搜索结果，正在生成回答")
                                    answer_started["value"] = True
                                text = event.get("text") or ""
                                full_text_for_db.append(text)
                                chunk_queue.put(("token", text))
                            elif event.get("type") == "search":
                                _progress("search", event.get("text") or "正在搜索网页")
                            elif event.get("type") == "reasoning":
                                _progress("reasoning", event.get("text") or "模型正在分析")
                            elif event.get("type") == "sources":
                                sources = event.get("sources") or []
                                if sources:
                                    names = [
                                        str(src.get("title") or src.get("domain") or "网页来源").strip()
                                        for src in sources[:3]
                                        if isinstance(src, dict)
                                    ]
                                    summary = "、".join(name for name in names if name)
                                    _progress(
                                        "search",
                                        f"已找到 {len(sources)} 个网页来源" + (f"：{summary}" if summary else ""),
                                    )
                            elif event.get("type") == "done":
                                parsed = event.get("payload") or {}
                                source_count = len(parsed.get("sources") or [])
                                if source_count:
                                    names = [
                                        str(src.get("title") or src.get("domain") or "网页来源").strip()
                                        for src in (parsed.get("sources") or [])[:3]
                                        if isinstance(src, dict)
                                    ]
                                    summary = "、".join(name for name in names if name)
                                    _progress(
                                        "search",
                                        f"联网搜索完成，整理出 {source_count} 个来源" + (f"：{summary}" if summary else ""),
                                    )
                                payload = {
                                    "content": parsed.get("content") or "模型没有返回可显示内容。",
                                    "note": chat_service.merge_response_notes(
                                        merged_note,
                                        "已使用模型内建联网搜索",
                                    ),
                                    "sources": [*merged_sources, *(parsed.get("sources") or [])],
                                    "rag_status": rag_bundle.get("rag_status") or "",
                                }
                                streamed_content = clean_response_text("".join(full_text_for_db))
                                if streamed_content and len(streamed_content) >= len(clean_response_text(payload["content"])):
                                    payload["content"] = streamed_content
                                final_content_for_db["value"] = payload["content"]
                                chunk_queue.put(("responses_done", payload))
                                return
                        if not stop_event.is_set():
                            chunk_queue.put(("end", None))
                    except Exception:
                        _progress("status", "内建联网搜索不可用，正在切换普通对话")
                        payload = chat_service.perform_chat(
                            req,
                            knowledge_context=rag_bundle.get("context_text") or "",
                            response_note=merged_note,
                            response_sources=merged_sources,
                            rag_status=rag_bundle.get("rag_status") or "",
                        )
                        final_content_for_db["value"] = payload.get("content") or ""
                        chunk_queue.put(("responses_done", payload))
                elif req.use_web_search and chat_service.supports_gemini_builtin_web_search(req.model):
                    try:
                        _progress("search", "正在调用 Gemini 联网搜索")
                        for event in ofox_gemini_search_service.stream_gemini_search_api(
                            model=req.model,
                            input_payload=messages,
                            reasoning_mode=req.reasoning_mode,
                            timeout=TEXT_TIMEOUT_SECONDS,
                        ):
                            if stop_event.is_set():
                                break
                            if event.get("type") == "token":
                                if not answer_started["value"]:
                                    _progress("reasoning", "已获得搜索结果，正在生成回答")
                                    answer_started["value"] = True
                                text = event.get("text") or ""
                                full_text_for_db.append(text)
                                chunk_queue.put(("token", text))
                            elif event.get("type") == "done":
                                parsed = event.get("payload") or {}
                                source_count = len(parsed.get("sources") or [])
                                if source_count:
                                    names = [
                                        str(src.get("title") or src.get("domain") or "网页来源").strip()
                                        for src in (parsed.get("sources") or [])[:3]
                                        if isinstance(src, dict)
                                    ]
                                    summary = "、".join(name for name in names if name)
                                    _progress(
                                        "search",
                                        f"联网搜索完成，整理出 {source_count} 个来源" + (f"：{summary}" if summary else ""),
                                    )
                                payload = {
                                    "content": parsed.get("content") or "模型没有返回可显示内容。",
                                    "note": chat_service.merge_response_notes(
                                        merged_note,
                                        "已使用模型内建联网搜索",
                                    ),
                                    "sources": [*merged_sources, *(parsed.get("sources") or [])],
                                    "rag_status": rag_bundle.get("rag_status") or "",
                                }
                                streamed_content = clean_response_text("".join(full_text_for_db))
                                if streamed_content and len(streamed_content) >= len(clean_response_text(payload["content"])):
                                    payload["content"] = streamed_content
                                final_content_for_db["value"] = payload["content"]
                                chunk_queue.put(("responses_done", payload))
                                return
                        if not stop_event.is_set():
                            chunk_queue.put(("end", None))
                    except Exception:
                        _progress("status", "Gemini 联网搜索不可用，正在切换普通对话")
                        payload = chat_service.perform_chat(
                            req,
                            knowledge_context=rag_bundle.get("context_text") or "",
                            response_note=merged_note,
                            response_sources=merged_sources,
                            rag_status=rag_bundle.get("rag_status") or "",
                        )
                        final_content_for_db["value"] = payload.get("content") or ""
                        chunk_queue.put(("responses_done", payload))
                else:
                    _progress("status", "正在请求模型")
                    for chunk in chat_service.stream_chat_completion(
                        model=req.model,
                        messages=messages,
                        reasoning_mode=req.reasoning_mode,
                        temperature=0.7,
                        timeout=TEXT_TIMEOUT_SECONDS,
                    ):
                        if stop_event.is_set():
                            break
                        if isinstance(chunk, dict):
                            if chunk.get("type") == "reasoning":
                                _progress("reasoning", chunk.get("text") or "模型正在分析")
                            continue
                        if not answer_started["value"]:
                            _progress("reasoning", "模型正在组织回答")
                            answer_started["value"] = True
                        full_text_for_db.append(str(chunk or ""))
                        chunk_queue.put(("token", chunk))
                    chunk_queue.put(("end", None))
                    return
            except Exception as exc:
                chunk_queue.put(("error", str(exc)))
                return
            finally:
                if stop_event.is_set():
                    return
                content = clean_response_text(final_content_for_db["value"] or "".join(full_text_for_db))
                if not content:
                    return
                try:
                    with get_session_factory()() as worker_db:
                        message_service.complete_assistant_message(
                            worker_db,
                            message_id=assistant_message.id,
                            content=content,
                        )
                        conv = conversation_service.get_conversation_for_user(
                            worker_db,
                            conversation.id,
                            conversation.user_id,
                        )
                        if conv:
                            conversation_service.touch_conversation(
                                worker_db,
                                conv,
                                model=req.model,
                                last_message_at=datetime.now(),
                            )
                except Exception:
                    logger.warning(
                        "[chat-stream] background complete after disconnect failed message_id=%s",
                        assistant_message.id,
                        exc_info=True,
                    )

        stream_thread = threading.Thread(target=_run_stream, daemon=True)
        stream_thread.start()

        full_text_parts: list[str] = []
        ended_error = False
        user_disconnect = False
        assistant_finalized = False
        last_out = time.monotonic()
        keepalive_after = max(5.0, WS_KEEPALIVE_SECONDS)
        loop = asyncio.get_running_loop()
        token_filter_buffer = ""
        token_filter_decided = False

        def _filter_initial_token(raw: str, *, force: bool = False) -> tuple[list[str], bool]:
            nonlocal token_filter_buffer, token_filter_decided
            if not raw:
                return [], token_filter_decided
            if token_filter_decided:
                return [raw], True

            token_filter_buffer += raw
            cleaned = _strip_leading_process_narration(token_filter_buffer)
            if cleaned != token_filter_buffer:
                token_filter_buffer = cleaned

            has_answer_signal = bool(cleaned.strip()) and (
                "\n\n" in cleaned
                or len(cleaned) >= 180
                or not PROCESS_HEADING_RE.match(cleaned.strip().split("\n", 1)[0])
            )
            if force or has_answer_signal:
                token_filter_decided = True
                out = token_filter_buffer
                token_filter_buffer = ""
                return ([out] if out else []), True
            return [], False

        try:
            while True:
                if await request.is_disconnected():
                    user_disconnect = True
                    break
                try:
                    kind, data = await loop.run_in_executor(
                        None, lambda: chunk_queue.get(timeout=0.1)
                    )
                except queue.Empty:
                    if (time.monotonic() - last_out) >= keepalive_after:
                        yield ": ping\n\n"
                        last_out = time.monotonic()
                    continue

                if kind == "token":
                    chunks, _ = _filter_initial_token(str(data or ""))
                    for chunk_text in chunks:
                        full_text_parts.append(chunk_text)
                        payload = json.dumps({"type": "token", "text": chunk_text}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                        last_out = time.monotonic()
                elif kind == "progress":
                    event_data = data or {}
                    event_type = str(event_data.get("kind") or "status")
                    payload = json.dumps(
                        {
                            "type": event_type,
                            "text": event_data.get("text") or "",
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
                    last_out = time.monotonic()
                elif kind == "error":
                    message_service.fail_assistant_message(
                        db,
                        message_id=assistant_message.id,
                        error_message=str(data or "stream error"),
                    )
                    assistant_finalized = True
                    payload = json.dumps({"type": "error", "detail": data}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                    ended_error = True
                    break
                elif kind == "responses_done":
                    full_text = clean_response_text((data or {}).get("content") or "")
                    merged_done_payload = json.dumps(
                        {
                            "type": "done",
                            "message_id": assistant_message.id,
                            "content": full_text,
                            "sources": (data or {}).get("sources") or [],
                            "note": (data or {}).get("note") or "",
                            "rag_status": (data or {}).get("rag_status") or "",
                            **effective_meta,
                        },
                        ensure_ascii=False,
                    )
                    message_service.complete_assistant_message(
                        db,
                        message_id=assistant_message.id,
                        content=full_text,
                    )
                    conversation_service.touch_conversation(
                        db,
                        conversation,
                        model=req.model,
                        last_message_at=datetime.now(),
                    )
                    assistant_finalized = True
                    yield f"data: {merged_done_payload}\n\n"
                    break
                elif kind == "end":
                    chunks, _ = _filter_initial_token("", force=True)
                    for chunk_text in chunks:
                        full_text_parts.append(chunk_text)
                        payload = json.dumps({"type": "token", "text": chunk_text}, ensure_ascii=False)
                        yield f"data: {payload}\n\n"
                        last_out = time.monotonic()
                    break

            if not ended_error and not user_disconnect and not assistant_finalized:
                if await request.is_disconnected():
                    user_disconnect = True
                else:
                    full_text = clean_response_text("".join(full_text_parts))
                    message_service.complete_assistant_message(
                        db,
                        message_id=assistant_message.id,
                        content=full_text,
                    )
                    conversation_service.touch_conversation(
                        db,
                        conversation,
                        model=req.model,
                        last_message_at=datetime.now(),
                    )
                    assistant_finalized = True
                    payload = json.dumps(
                        {
                            "type": "done",
                            "message_id": assistant_message.id,
                            "content": full_text,
                            "sources": merged_sources,
                            "note": stream_note,
                            "rag_status": rag_bundle.get("rag_status") or "",
                            **effective_meta,
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
        finally:
            if not assistant_finalized and not user_disconnect:
                reason = "客户端断开连接。" if user_disconnect else "流式响应未正常完成。"
                message_service.fail_assistant_message(
                    db,
                    message_id=assistant_message.id,
                    error_message=reason,
                )
            if not user_disconnect:
                stop_event.set()
                stream_thread.join(timeout=2)
            reset_ai_request_context(rid_t, att_t, im_t)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        raw = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    try:
        websocket.session["auth_ok"] = True
    except (AttributeError, KeyError, TypeError):
        pass

    try:
        req = ChatRequest(**raw)
    except Exception as e:
        await websocket.send_json({"type": "error", "detail": f"参数错误: {e}"})
        await websocket.close()
        return

    rid_t, att_t, im_t = set_ai_request_context(req.attachment_ids or [], None)
    bound_rid = get_ai_request_id()
    att_list = req.attachment_ids or []
    try:
        try:
            messages = chat_service.build_text_chat_messages(
                system_prompt=chat_service.resolve_chat_system_prompt(req.system_prompt),
                summary=req.summary or "",
                history_messages=req.history_messages or [],
                current_user_content=chat_service.build_current_user_message_content(
                    req.prompt,
                    req.attachment_ids,
                ),
            )

            chunk_queue: queue.Queue = queue.Queue()
            stop_event = threading.Event()

            def _run_stream():
                _ai_request_id_var.set(bound_rid)
                _ai_log_attachment_ids_var.set(att_list)
                _ai_image_mode_var.set("")
                try:
                    for chunk in chat_service.stream_chat_completion(
                        model=req.model,
                        messages=messages,
                        reasoning_mode=req.reasoning_mode,
                        temperature=0.7,
                        timeout=TEXT_TIMEOUT_SECONDS,
                    ):
                        if stop_event.is_set():
                            break
                        chunk_queue.put(("token", chunk))
                    chunk_queue.put(("end", None))
                except Exception as exc:
                    chunk_queue.put(("error", str(exc)))

            stream_thread = threading.Thread(target=_run_stream, daemon=True)
            stream_thread.start()

            full_text_parts: list[str] = []
            stopped = False

            async def _listen_for_stop():
                nonlocal stopped
                try:
                    while not stopped:
                        msg = await websocket.receive_json()
                        if isinstance(msg, dict) and msg.get("type") == "stop":
                            stopped = True
                            stop_event.set()
                            break
                except (WebSocketDisconnect, Exception):
                    stopped = True
                    stop_event.set()

            stop_task = asyncio.create_task(_listen_for_stop())

            last_ws_activity = time.monotonic()
            keepalive_after = max(5.0, WS_KEEPALIVE_SECONDS)

            while True:
                try:
                    kind, data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: chunk_queue.get(timeout=0.1)
                    )
                except queue.Empty:
                    if stopped:
                        break
                    if (time.monotonic() - last_ws_activity) >= keepalive_after and not stopped:
                        try:
                            await websocket.send_json({"type": "keepalive"})
                            last_ws_activity = time.monotonic()
                        except (WebSocketDisconnect, Exception):
                            stopped = True
                            stop_event.set()
                            break
                    continue

                if kind == "token":
                    full_text_parts.append(data)
                    if not stopped:
                        try:
                            await websocket.send_json({"type": "token", "text": data})
                            last_ws_activity = time.monotonic()
                        except (WebSocketDisconnect, Exception):
                            stopped = True
                            stop_event.set()
                            break
                elif kind == "error":
                    if not stopped:
                        try:
                            await websocket.send_json({"type": "error", "detail": data})
                        except Exception:
                            pass
                    break
                elif kind == "end":
                    break

            stop_task.cancel()
            stream_thread.join(timeout=2)

            full_text = clean_response_text("".join(full_text_parts))
            msg_type = "stopped" if stopped else "done"
            try:
                await websocket.send_json({"type": msg_type, "content": full_text})
            except (WebSocketDisconnect, Exception):
                pass

        except Exception as e:
            logger.exception("WS chat error: %s", e)
            try:
                await websocket.send_json({"type": "error", "detail": str(e)})
            except Exception:
                pass
    finally:
        reset_ai_request_context(rid_t, att_t, im_t)

    try:
        await websocket.close()
    except Exception:
        pass
