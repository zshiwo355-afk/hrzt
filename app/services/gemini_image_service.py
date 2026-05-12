"""Gemini / Nano Banana 系列在 Ofox 上的图生图：Gemini Native generateContent（非 chat/completions）。"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import requests

from app.ai_context import (
    _ai_log_req,
    _ai_log_resp,
    _ai_log_attachment_ids_var,
    _decode_data_url_bytes_size,
    get_ai_request_id,
)
from app.config import IMAGE_TASK_TIMEOUT_SECONDS
from app.logging_config import logger
from app.providers import ofox
from app.providers.ofox_gemini import gemini_native_generate_content_endpoint


_GEMINI_IMAGE_MODEL_ALIASES = {
    "google/gemini-2.5-flash-image-preview": "google/gemini-2.5-flash-image",
    "google/nano-banana": "google/gemini-2.5-flash-image",
    "nano-banana": "google/gemini-2.5-flash-image",
}


def normalize_gemini_image_model_id(model: str) -> str:
    raw = (model or "").strip()
    return _GEMINI_IMAGE_MODEL_ALIASES.get(raw.lower(), raw)


def _normalize_to_images_generations_shape(image_ref: str) -> dict:
    if image_ref.startswith("http") or image_ref.startswith("data:"):
        if image_ref.startswith("data:"):
            if ";base64," in image_ref:
                b64 = image_ref.split(";base64,", 1)[1]
                return {"data": [{"b64_json": b64}]}
        return {"data": [{"url": image_ref}]}
    if image_ref:
        return {"data": [{"b64_json": image_ref}]}
    return {"data": []}


def _parse_data_url(ref: str) -> tuple[str, str]:
    if not ref.startswith("data:"):
        raise ValueError("not a data URL")
    head, _, b64 = ref.partition(",")
    m = re.match(r"data:([^;,]+)", head)
    mime = (m.group(1).strip() if m else "") or "application/octet-stream"
    return mime, b64.strip()


def _ref_to_inline_part(ref: str, timeout: int) -> dict[str, Any]:
    """单张参考图 -> Gemini Native parts 元素（inline_data）。"""
    r = (ref or "").strip()
    if not r:
        raise RuntimeError("empty reference image")

    if r.startswith("data:"):
        mime, b64 = _parse_data_url(r)
        if not b64:
            raise RuntimeError("data URL has empty payload")
        return {"inline_data": {"mime_type": mime, "data": b64}}

    if r.startswith("http://") or r.startswith("https://"):
        try:
            resp = ofox.ofox_request("GET", r, timeout=min(120, max(10, timeout)))
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"fetch ref image failed: {e!r}") from e
        if resp.status_code != 200:
            raise RuntimeError(f"fetch ref image HTTP {resp.status_code}")
        raw = resp.content
        ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        mime = ct if ct.startswith("image/") else "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        return {"inline_data": {"mime_type": mime, "data": b64}}

    return {"inline_data": {"mime_type": "image/png", "data": r}}


def _part_image_refs(part: dict[str, Any]) -> list[str]:
    """从单个 part 提取图片 URL 或 data URL（兼容 inlineData / inline_data / fileData）。"""
    out: list[str] = []
    if not isinstance(part, dict):
        return out

    inline = part.get("inlineData") or part.get("inline_data")
    if isinstance(inline, dict):
        mime = (
            inline.get("mimeType")
            or inline.get("mime_type")
            or "image/png"
        )
        b64 = inline.get("data")
        if isinstance(b64, str) and b64.strip():
            out.append(f"data:{mime};base64,{b64.strip()}")

    fd = part.get("fileData") or part.get("file_data")
    if isinstance(fd, dict):
        uri = fd.get("fileUri") or fd.get("file_uri")
        if isinstance(uri, str) and uri.strip():
            out.append(uri.strip())

    return out


def _collect_images_gemini_native(data: dict[str, Any]) -> list[str]:
    found: list[str] = []
    cands = data.get("candidates")
    if not isinstance(cands, list):
        return found
    for cand in cands:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            found.extend(_part_image_refs(part))
    return found


def _summarize_parts(parts: Any, *, max_parts: int = 16) -> str:
    if parts is None:
        return "parts=None"
    if not isinstance(parts, list):
        return f"parts_type={type(parts).__name__}"
    bits: list[str] = []
    for i, p in enumerate(parts[:max_parts]):
        if not isinstance(p, dict):
            bits.append(f"[{i}]non-dict")
            continue
        keys = sorted(p.keys())
        kinds: list[str] = []
        if "text" in p:
            t = p.get("text")
            kinds.append(
                f"text(len={len(t)})" if isinstance(t, str) else "text(non-str)"
            )
        if "inlineData" in p or "inline_data" in p:
            kinds.append("inline_image")
        if "fileData" in p or "file_data" in p:
            kinds.append("file_ref")
        if "functionCall" in p or "function_call" in p:
            kinds.append("function_call")
        bits.append(
            f"[{i}]keys={keys} " + (",".join(kinds) if kinds else "no_known_kind")
        )
    if len(parts) > max_parts:
        bits.append(f"...(+{len(parts) - max_parts} parts)")
    return "; ".join(bits)


def _log_no_image_parse(data: dict[str, Any]) -> None:
    top_keys = sorted(data.keys()) if isinstance(data, dict) else [type(data).__name__]
    logger.info(
        "[api-gemini-native] no_image_parse top_level_keys=%s",
        top_keys,
    )
    c0 = None
    cands = data.get("candidates") if isinstance(data, dict) else None
    if isinstance(cands, list) and cands:
        c0 = cands[0]
    parts = None
    if isinstance(c0, dict):
        content = c0.get("content")
        if isinstance(content, dict):
            parts = content.get("parts")
    logger.info(
        "[api-gemini-native] no_image_parse candidates[0].content.parts_summary=%s",
        _summarize_parts(parts),
    )


def call_gemini_native_image_api(
    model: str,
    prompt: str,
    ref_data_urls: list[str],
    *,
    timeout: int = 0,
) -> dict:
    """
    POST Ofox Gemini Native generateContent；返回结构与 extract_image_result 兼容。
    """
    urls = [u for u in (ref_data_urls or []) if isinstance(u, str) and u.strip()][:8]
    if not urls:
        raise RuntimeError("Gemini 多模态图生图需要至少一张参考图")

    if not timeout:
        timeout = int(IMAGE_TASK_TIMEOUT_SECONDS)

    normalized_model = normalize_gemini_image_model_id(model)
    endpoint = gemini_native_generate_content_endpoint(normalized_model)
    att_ids = _ai_log_attachment_ids_var.get() or []
    has_attachments = bool(att_ids)
    prompt_preview = (prompt or "").strip()
    prompt100 = prompt_preview[:100]

    parts_body: list[dict[str, Any]] = []
    for u in urls:
        parts_body.append(_ref_to_inline_part(u, timeout))
    parts_body.append(
        {
            "text": prompt_preview
            or "请根据参考图生成或编辑成目标画面，直接输出图像，不要只描述。",
        }
    )

    payload: dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": parts_body,
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    logger.info(
        "[api-gemini-native] phase=request request_id=%s model=%s normalized_model=%s endpoint=%s "
        "has_attachments=%s ref_images_count=%s prompt100=%r",
        get_ai_request_id(),
        model,
        normalized_model,
        endpoint,
        has_attachments,
        len(urls),
        prompt100,
    )
    _ai_log_req(
        "image",
        normalized_model,
        prompt_preview,
        has_image=True,
        image_sizes=[_decode_data_url_bytes_size(u) for u in urls[:4]],
        provider="ofox",
    )

    try:
        resp = ofox.ofox_request(
            "POST",
            endpoint,
            headers={
                "x-goog-api-key": ofox.ofox_api_key(),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        err = repr(e)
        logger.info(
            "[api-gemini-native] phase=response request_id=%s model=%s endpoint=%s "
            "status_code=None parsed_image_count=0 success=False error=%s",
            get_ai_request_id(),
            normalized_model,
            endpoint,
            err,
        )
        _ai_log_resp(
            "image",
            normalized_model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err) from e
    except requests.exceptions.RequestException as e:
        err = repr(e)
        logger.info(
            "[api-gemini-native] phase=response request_id=%s model=%s endpoint=%s "
            "status_code=None parsed_image_count=0 success=False error=%s",
            get_ai_request_id(),
            normalized_model,
            endpoint,
            err,
        )
        _ai_log_resp(
            "image",
            normalized_model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err) from e

    sc = resp.status_code
    try:
        raw_body = (resp.text or "")[:4000]
    except Exception:
        raw_body = ""

    if sc != 200:
        first_error = ofox.extract_error_message_from_response(resp)
        err = f"HTTP {sc}; parsed={first_error!r}; body={raw_body!r}"
        logger.info(
            "[api-gemini-native] phase=response request_id=%s model=%s endpoint=%s "
            "status_code=%s parsed_image_count=0 success=False",
            get_ai_request_id(),
            normalized_model,
            endpoint,
            sc,
        )
        _ai_log_resp(
            "image",
            normalized_model,
            success=False,
            degraded=False,
            status_code=sc,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err)

    try:
        data = resp.json()
    except Exception as e:
        logger.info(
            "[api-gemini-native] phase=response request_id=%s model=%s endpoint=%s "
            "status_code=%s parsed_image_count=0 success=False error=json_decode",
            get_ai_request_id(),
            normalized_model,
            endpoint,
            sc,
        )
        raise RuntimeError(f"invalid JSON from Gemini Native: {e!r}") from e

    if not isinstance(data, dict):
        logger.info(
            "[api-gemini-native] phase=response request_id=%s model=%s endpoint=%s "
            "status_code=%s parsed_image_count=0 success=False",
            get_ai_request_id(),
            normalized_model,
            endpoint,
            sc,
        )
        raise RuntimeError(f"Gemini Native 响应顶层非 object: {type(data).__name__}")

    imgs = _collect_images_gemini_native(data)
    parsed_count = len(imgs)
    primary = imgs[0] if imgs else ""

    logger.info(
        "[api-gemini-native] phase=response request_id=%s model=%s endpoint=%s "
        "status_code=%s parsed_image_count=%s success=%s",
        get_ai_request_id(),
        normalized_model,
        endpoint,
        sc,
        parsed_count,
        bool(primary),
    )

    if not primary:
        _log_no_image_parse(data)
        snippet = json.dumps(data, ensure_ascii=False)[:2000]
        _ai_log_resp(
            "image",
            normalized_model,
            success=False,
            degraded=False,
            status_code=sc,
            error_full="Gemini Native 响应中未解析到图片字段",
            provider="ofox",
        )
        raise RuntimeError(
            f"Gemini Native 响应中未解析到图片。响应摘要: {snippet}"
        )

    _ai_log_resp(
        "image",
        normalized_model,
        success=True,
        degraded=False,
        status_code=sc,
        error_full="",
        provider="ofox",
    )
    return _normalize_to_images_generations_shape(primary)
