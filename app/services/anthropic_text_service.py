"""Claude / Anthropic native text adapter via OFOX."""
from __future__ import annotations

import json
import re
from typing import Any, Iterator

import requests
from fastapi import HTTPException

from app.config import TEXT_TIMEOUT_SECONDS
from app.providers import ofox
from app.services.attachment_service import clean_response_text

ANTHROPIC_MAX_TOKENS = 16384
_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+);base64,(?P<data>.+)$", re.IGNORECASE | re.DOTALL)


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n\n".join(parts).strip()
    return ""


def _anthropic_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        text = content.strip()
        return [{"type": "text", "text": text}] if text else []
    if not isinstance(content, list):
        return []

    blocks: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        part_type = str(item.get("type") or "").strip()
        if part_type == "text":
            text = str(item.get("text") or "").strip()
            if text:
                blocks.append({"type": "text", "text": text})
            continue
        if part_type == "image_url":
            image_obj = item.get("image_url")
            image_url = ""
            if isinstance(image_obj, dict):
                image_url = str(image_obj.get("url") or "").strip()
            else:
                image_url = str(image_obj or "").strip()
            matched = _DATA_URL_RE.match(image_url)
            if not matched:
                continue
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": matched.group("mime"),
                        "data": matched.group("data"),
                    },
                }
            )
    return blocks


def split_system_and_messages(messages: list[dict]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out_messages: list[dict[str, Any]] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        if role == "system":
            text = _text_from_content(content).strip()
            if text:
                system_parts.append(text)
            continue
        if role not in {"user", "assistant"}:
            continue
        blocks = _anthropic_content_blocks(content)
        if not blocks:
            continue
        out_messages.append({"role": role, "content": blocks})
    return "\n\n".join(system_parts).strip(), out_messages


def _build_payload(
    *,
    model: str,
    messages: list[dict],
    temperature: float,
    stream: bool,
    anthropic_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_text, anthropic_messages = split_system_and_messages(messages)
    payload: dict[str, Any] = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "temperature": temperature,
    }
    if system_text:
        payload["system"] = system_text
    if anthropic_extra:
        payload.update(anthropic_extra)
    if stream:
        payload["stream"] = True
    return payload


def _join_text_blocks(data: dict) -> str:
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") == "text":
            text = str(block.get("text") or "")
            if text:
                parts.append(text)
    return clean_response_text("".join(parts))


def call_anthropic_messages_api(
    *,
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    timeout: int = TEXT_TIMEOUT_SECONDS,
    anthropic_extra: dict[str, Any] | None = None,
) -> str:
    payload = _build_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=False,
        anthropic_extra=anthropic_extra,
    )
    try:
        resp = ofox.ofox_request(
            "POST",
            ofox.ofox_anthropic_messages_url(),
            headers=ofox.ofox_anthropic_headers(),
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        err = repr(exc)
        raise HTTPException(status_code=504, detail=err) from exc
    except requests.exceptions.RequestException as exc:
        err = repr(exc)
        raise HTTPException(status_code=502, detail=err) from exc

    if resp.status_code != 200:
        err_body = ofox.extract_error_message_from_response(resp)
        try:
            raw_body = (resp.text or "")[:4000]
        except Exception:
            raw_body = ""
        err = f"HTTP {resp.status_code}; parsed={err_body!r}; body={raw_body!r}"
        raise HTTPException(status_code=500, detail=err)

    data = resp.json()
    return _join_text_blocks(data)


def stream_anthropic_messages_api(
    *,
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    timeout: int = TEXT_TIMEOUT_SECONDS,
    anthropic_extra: dict[str, Any] | None = None,
) -> Iterator[str]:
    payload = _build_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=True,
        anthropic_extra=anthropic_extra,
    )
    try:
        resp = ofox.ofox_request(
            "POST",
            ofox.ofox_anthropic_messages_url(),
            headers=ofox.ofox_anthropic_headers(),
            json=payload,
            timeout=timeout,
            stream=True,
        )
    except requests.exceptions.Timeout as exc:
        err = repr(exc)
        raise RuntimeError(err) from exc
    except requests.exceptions.RequestException as exc:
        err = repr(exc)
        raise RuntimeError(err) from exc

    if resp.status_code != 200:
        try:
            raw_body = (resp.text or "")[:4000]
        except Exception:
            raw_body = ""
        parsed = ofox.extract_error_message_from_response(resp)
        err = f"HTTP {resp.status_code}; parsed={parsed!r}; body={raw_body!r}"
        raise RuntimeError(err)

    resp.encoding = "utf-8"
    event_name = ""
    for line in resp.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if not line:
            event_name = ""
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
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

        event_type = str(event.get("type") or event_name or "").strip()
        if event_type == "content_block_delta":
            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            if str(delta.get("type") or "") == "text_delta":
                text = str(delta.get("text") or "")
                if text:
                    yield text
            continue
        if event_type == "error":
            error_obj = event.get("error") if isinstance(event.get("error"), dict) else {}
            raise RuntimeError(str(error_obj.get("message") or error_obj or "anthropic stream failed"))
        if event_type == "message_stop":
            break
