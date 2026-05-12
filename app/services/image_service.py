"""图片生成统一入口：按模型 adapter 分流到 Ofox OpenAI images、OpenAI edits 或 Gemini Native generateContent。"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Any, Optional

import requests

from app.ai_context import (
    _ai_log_req,
    _ai_log_resp,
    _ai_log_attachment_ids_var,
    _decode_data_url_bytes_size,
    get_ai_request_id,
)
from app.config import IMAGE_EDITS_TIMEOUT_SECONDS, IMAGE_TASK_TIMEOUT_SECONDS
from app.logging_config import logger
from app.providers import ofox
from app.providers.ofox_gemini import gemini_native_generate_content_endpoint
from app.services.model_service import image_route_meta
from app.services.attachment_service import read_attachment_bytes, read_attachment_meta_any

# 参考图轻量预处理（仅 edits）
_EDIT_REF_MAX_BYTES = 3 * 1024 * 1024
_EDIT_REF_MAX_LONG_EDGE = 2048

# /images/edits multipart 文件字段名（Ofox 文档：单数 image）
_IMAGE_EDITS_MULTIPART_FILE_FIELD = "image"
_GPT_IMAGE_2_ID = "openai/gpt-image-2"
_OPENAI_IMAGE_EDIT_MODELS = {_GPT_IMAGE_2_ID}


def build_image_reference_data_urls(attachment_ids: list[str]) -> list[str]:
    logger.info("[route-enter] build_image_reference_data_urls attachment_ids=%r", attachment_ids)
    results = []

    for attachment_id in attachment_ids:
        meta = read_attachment_meta_any(attachment_id)
        if not meta:
            continue

        if meta["category"] != "image":
            continue

        try:
            raw = read_attachment_bytes(meta)
            if raw is None:
                continue
            mime_type = meta.get("mime_type") or "image/png"
            encoded = base64.b64encode(raw).decode("utf-8")
            results.append(f"data:{mime_type};base64,{encoded}")
            logger.info(
                "[ref-image-build] attachment_id=%s mime=%s bytes=%s",
                attachment_id,
                mime_type,
                len(raw),
            )
        except Exception:
            continue

    return results[:4]


def extract_image_result(data: dict) -> str:
    items = data.get("data")

    if isinstance(items, list) and items:
        item = items[0] or {}
        if isinstance(item, dict):
            if item.get("url"):
                return item["url"]

            b64 = (
                item.get("b64_json")
                or item.get("base64")
                or item.get("image_base64")
            )
            if b64:
                return f"data:image/png;base64,{b64}"

    if data.get("url"):
        return data["url"]

    b64 = data.get("b64_json") or data.get("base64") or data.get("image_base64")
    if b64:
        return f"data:image/png;base64,{b64}"

    return ""


def _log_images_generations_body(primary_payload: dict, ref_list: list[str]) -> None:
    """记录将发往 /v1/images/generations 的 JSON 摘要（不记录完整 data URL / base64）。"""
    pr = primary_payload.get("prompt")
    pr_log = pr if isinstance(pr, str) else pr
    if isinstance(pr_log, str) and len(pr_log) > 500:
        pr_log = pr_log[:500] + "…"

    ref0_prefix = ""
    if ref_list and isinstance(ref_list[0], str):
        ref0_prefix = ref_list[0][:30]

    logger.info(
        "[api-gen-body] model=%r prompt=%r size=%r n=%r reference_images_count=%d "
        "reference_images[0]_prefix30=%r",
        primary_payload.get("model"),
        pr_log,
        primary_payload.get("size"),
        primary_payload.get("n"),
        len(ref_list),
        ref0_prefix,
    )


def call_openai_image_generation_api(
    payload: dict,
    ref_images: list[str],
    timeout: int = 0,
) -> dict:
    """POST OFOX /v1/images/generations（OpenAI 兼容）。无参考图时 ref_images 应为空。"""
    logger.info(
        "[route-enter] call_openai_image_generation_api model=%r ref_images_count=%s",
        payload.get("model"),
        len(ref_images or []),
    )
    if not timeout:
        timeout = IMAGE_TASK_TIMEOUT_SECONDS

    endpoint = f"{ofox.ofox_base_url()}/images/generations"
    model = str(payload.get("model") or "")
    prompt_preview = str(payload.get("prompt") or "")
    ref_list = list(ref_images or [])
    ref_count = len(ref_list)
    att_ids = _ai_log_attachment_ids_var.get() or []
    has_attachments = bool(att_ids)
    prompt100 = (prompt_preview or "")[:100]

    primary_payload = dict(payload)
    if ref_list:
        primary_payload["reference_images"] = ref_list

    _log_images_generations_body(primary_payload, ref_list)

    logger.info(
        "[api-gen] phase=request request_id=%s endpoint=%s model=%s has_attachments=%s "
        "reference_images_count=%s prompt100=%r status_code=%s success=%s error=%s",
        get_ai_request_id(),
        endpoint,
        model,
        has_attachments,
        ref_count,
        prompt100,
        None,
        None,
        "",
    )
    _ai_log_req(
        "image",
        model,
        prompt_preview,
        has_image=bool(ref_list),
        image_sizes=[_decode_data_url_bytes_size(u) for u in ref_list[:4]],
        provider="ofox",
    )

    headers = {
        "Authorization": f"Bearer {ofox.ofox_api_key()}",
        "Content-Type": "application/json",
    }

    try:
        resp = ofox.ofox_request(
            "POST",
            endpoint,
            headers=headers,
            json=primary_payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        err = repr(e)
        logger.info(
            "[api-gen] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
            "reference_images_count=%s prompt100=%r status_code=%s success=%s error=%s",
            get_ai_request_id(),
            endpoint,
            model,
            has_attachments,
            ref_count,
            prompt100,
            None,
            False,
            err,
        )
        _ai_log_resp(
            "image",
            model,
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
            "[api-gen] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
            "reference_images_count=%s prompt100=%r status_code=%s success=%s error=%s",
            get_ai_request_id(),
            endpoint,
            model,
            has_attachments,
            ref_count,
            prompt100,
            None,
            False,
            err,
        )
        _ai_log_resp(
            "image",
            model,
            success=False,
            degraded=False,
            status_code=None,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err) from e

    sc = resp.status_code
    if sc == 200:
        logger.info(
            "[api-gen] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
            "reference_images_count=%s prompt100=%r status_code=%s success=%s error=%s",
            get_ai_request_id(),
            endpoint,
            model,
            has_attachments,
            ref_count,
            prompt100,
            sc,
            True,
            "",
        )
        _ai_log_resp(
            "image",
            model,
            success=True,
            degraded=False,
            status_code=sc,
            error_full="",
            provider="ofox",
        )
        return resp.json()

    try:
        raw_body = (resp.text or "")[:4000]
    except Exception:
        raw_body = ""
    first_error = ofox.extract_error_message_from_response(resp)
    err = f"HTTP {sc}; parsed={first_error!r}; body={raw_body!r}"
    logger.info(
        "[api-gen] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
        "reference_images_count=%s prompt100=%r status_code=%s success=%s error=%s",
        get_ai_request_id(),
        endpoint,
        model,
        has_attachments,
        ref_count,
        prompt100,
        sc,
        False,
        err,
    )
    _ai_log_resp(
        "image",
        model,
        success=False,
        degraded=False,
        status_code=sc,
        error_full=err,
        provider="ofox",
    )
    raise RuntimeError(err)


def _seedream_reference_payloads(payload: dict, ref_images: list[str]) -> list[tuple[str, dict]]:
    refs = [u for u in (ref_images or []) if isinstance(u, str) and u.strip()][:10]
    base = dict(payload)
    if not refs:
        return [("text_only", base)]
    return [
        ("reference_images", {**base, "reference_images": refs}),
        ("images", {**base, "images": refs}),
        ("image", {**base, "image": refs}),
    ]


def _seedream_reference_error_is_retryable(status_code: int, body: str, parsed_msg: str) -> bool:
    if status_code not in (400, 422):
        return False
    blob = f"{body or ''} {parsed_msg or ''}".lower()
    return any(
        key in blob
        for key in (
            "image",
            "images",
            "reference_images",
            "invalid parameter",
            "unsupported parameter",
            "unknown field",
            "extra inputs",
            "bad request",
        )
    )


def call_seedream_image_generation_api(
    payload: dict,
    ref_images: list[str],
    timeout: int = 0,
) -> dict:
    """POST OFOX /v1/images/generations for Seedream. Try common reference-image field names."""
    if not timeout:
        timeout = IMAGE_TASK_TIMEOUT_SECONDS

    endpoint = f"{ofox.ofox_base_url()}/images/generations"
    model = str(payload.get("model") or "")
    prompt_preview = str(payload.get("prompt") or "")
    ref_list = list(ref_images or [])
    att_ids = _ai_log_attachment_ids_var.get() or []
    has_attachments = bool(att_ids)
    prompt100 = (prompt_preview or "")[:100]

    headers = {
        "Authorization": f"Bearer {ofox.ofox_api_key()}",
        "Content-Type": "application/json",
    }

    last_err = ""
    for variant, body in _seedream_reference_payloads(payload, ref_list):
        _log_images_generations_body(body, ref_list)
        logger.info(
            "[api-seedream] phase=request request_id=%s endpoint=%s variant=%s model=%s "
            "has_attachments=%s reference_images_count=%s prompt100=%r",
            get_ai_request_id(),
            endpoint,
            variant,
            model,
            has_attachments,
            len(ref_list),
            prompt100,
        )
        _ai_log_req(
            "image",
            model,
            prompt_preview,
            has_image=bool(ref_list),
            image_sizes=[_decode_data_url_bytes_size(u) for u in ref_list[:4]],
            provider="ofox",
        )

        try:
            resp = ofox.ofox_request(
                "POST",
                endpoint,
                headers=headers,
                json=body,
                timeout=timeout,
            )
        except requests.exceptions.RequestException as e:
            err = repr(e)
            _ai_log_resp(
                "image",
                model,
                success=False,
                degraded=False,
                status_code=None,
                error_full=err,
                provider="ofox",
            )
            raise RuntimeError(err) from e

        sc = resp.status_code
        if sc == 200:
            logger.info(
                "[api-seedream] phase=response request_id=%s endpoint=%s variant=%s model=%s "
                "reference_images_count=%s status_code=%s success=True",
                get_ai_request_id(),
                endpoint,
                variant,
                model,
                len(ref_list),
                sc,
            )
            _ai_log_resp(
                "image",
                model,
                success=True,
                degraded=False,
                status_code=sc,
                error_full="",
                provider="ofox",
            )
            return resp.json()

        raw_body = (resp.text or "")[:4000]
        first_error = ofox.extract_error_message_from_response(resp)
        last_err = f"HTTP {sc}; variant={variant!r}; parsed={first_error!r}; body={raw_body!r}"
        logger.info(
            "[api-seedream] phase=response request_id=%s endpoint=%s variant=%s model=%s "
            "reference_images_count=%s status_code=%s success=False error=%s",
            get_ai_request_id(),
            endpoint,
            variant,
            model,
            len(ref_list),
            sc,
            last_err,
        )
        if variant != "images" and _seedream_reference_error_is_retryable(sc, raw_body, first_error):
            continue
        _ai_log_resp(
            "image",
            model,
            success=False,
            degraded=False,
            status_code=sc,
            error_full=last_err,
            provider="ofox",
        )
        raise RuntimeError(last_err)

    raise RuntimeError(last_err or "Seedream image generation failed")


def _edits_ref_output_name(index: int, ext: str) -> str:
    return f"ref{index}{ext}"


def _pil_image_needs_alpha_channel(im: Any) -> bool:
    """是否应保留 PNG（含有效透明/半透明）。"""
    if im.mode == "P":
        return "transparency" in im.info
    if im.mode in ("RGBA", "LA"):
        alpha = im.split()[-1]
        return alpha.getextrema() != (255, 255)
    return False


def _preprocess_edits_reference_bytes(
    raw: bytes,
    mime_hint: str,
    index: int,
) -> tuple[str, bytes, str]:
    """
    仅用于 /images/edits 的参考图：长边封顶、>3MB 压 JPEG（无透明）或压 PNG。
    返回 (filename, body, mime)。
    """
    from PIL import Image

    orig_len = len(raw)
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception as e:
        logger.warning(
            "[api-edit-ref-pre] index=%d pil_open_failed orig_bytes=%s after_bytes=%s err=%s",
            index,
            orig_len,
            orig_len,
            repr(e),
        )
        ext = ".png" if "png" in mime_hint.lower() else ".jpg"
        return (_edits_ref_output_name(index, ext), raw, mime_hint)

    w, h = im.size
    long_in = max(w, h)
    need_resize = long_in > _EDIT_REF_MAX_LONG_EDGE
    need_shrink = orig_len > _EDIT_REF_MAX_BYTES

    if not need_resize and not need_shrink:
        logger.info(
            "[api-edit-ref-pre] index=%d unchanged orig_bytes=%s after_bytes=%s long_edge=%s",
            index,
            orig_len,
            orig_len,
            long_in,
        )
        ext = ".png" if "png" in mime_hint.lower() else ".jpg" if ("jpeg" in mime_hint.lower() or "jpg" in mime_hint.lower()) else ".webp" if "webp" in mime_hint.lower() else ".bin"
        return (_edits_ref_output_name(index, ext), raw, mime_hint)

    if need_resize:
        scale = _EDIT_REF_MAX_LONG_EDGE / float(long_in)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)

    keep_png = _pil_image_needs_alpha_channel(im)
    out_buf = io.BytesIO()
    if keep_png:
        if im.mode == "P":
            cur = im.convert("RGBA")
        elif im.mode == "LA":
            cur = im.convert("RGBA")
        elif im.mode == "RGBA":
            cur = im
        else:
            cur = im.convert("RGBA")
        out_bytes = b""
        for _ in range(16):
            out_buf.seek(0)
            out_buf.truncate(0)
            cur.save(out_buf, format="PNG", optimize=True)
            out_bytes = out_buf.getvalue()
            if len(out_bytes) <= _EDIT_REF_MAX_BYTES:
                break
            w2, h2 = cur.size
            if min(w2, h2) <= 8:
                break
            cur = cur.resize(
                (max(1, int(w2 * 0.88)), max(1, int(h2 * 0.88))),
                Image.Resampling.LANCZOS,
            )
        logger.info(
            "[api-edit-ref-pre] index=%d format=PNG orig_bytes=%s after_bytes=%s",
            index,
            orig_len,
            len(out_bytes),
        )
        return (_edits_ref_output_name(index, ".png"), out_bytes, "image/png")

    rgb = im.convert("RGB")
    out_bytes = b""
    for q in (85, 78, 72, 65, 58, 52, 45):
        out_buf.seek(0)
        out_buf.truncate(0)
        rgb.save(out_buf, format="JPEG", quality=q, optimize=True)
        out_bytes = out_buf.getvalue()
        if len(out_bytes) <= _EDIT_REF_MAX_BYTES:
            break
    logger.info(
        "[api-edit-ref-pre] index=%d format=JPEG orig_bytes=%s after_bytes=%s",
        index,
        orig_len,
        len(out_bytes),
    )
    return (_edits_ref_output_name(index, ".jpg"), out_bytes, "image/jpeg")


def _decode_data_url_to_file_tuple(data_url: str, index: int) -> tuple[str, bytes, str]:
    """data URL → (filename, raw_bytes, mime)。"""
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        raise ValueError("reference must be a data: URL")
    head, sep, b64part = data_url.partition(",")
    if not sep:
        raise ValueError("malformed data URL")
    meta = head[5:].strip()
    mime = "application/octet-stream"
    if ";" in meta:
        mime = (meta.split(";", 1)[0] or "").strip() or mime
    else:
        mime = meta or mime
    raw = base64.b64decode(b64part, validate=False)
    ml = mime.lower()
    if "png" in ml:
        ext = ".png"
    elif "webp" in ml:
        ext = ".webp"
    elif "jpeg" in ml or "jpg" in ml:
        ext = ".jpg"
    else:
        ext = ".bin"
    return (f"ref{index}{ext}", raw, mime)


def _request_content_type_sent(resp: requests.Response) -> str:
    try:
        h = getattr(resp.request, "headers", None)
        if h is not None:
            return str(h.get("Content-Type") or "")
    except Exception:
        pass
    return ""


def _edits_upstream_suggests_timeout(status_code: int, body: str, parsed_msg: str) -> bool:
    if status_code == 408:
        return True
    blob = f"{body} {parsed_msg}".lower()
    return "the operation was timeout" in blob or "operation was timeout" in blob


def _edits_timeout_user_message(wait_seconds: int, raw_error: str) -> str:
    friendly = (
        f"上游图片编辑处理超时。已等待 {wait_seconds} 秒。建议：\n"
        "1. 改用 GPT Image 1.5\n"
        "2. 简化编辑要求\n"
        "3. 降低图片尺寸后重试"
    )
    return f"{friendly}\n---原始错误---\n{raw_error}"


# /images/edits：429/503/overloaded 退避重试（最多 3 次重试 = 4 次请求）
_EDITS_OVERLOAD_RETRY_WAITS_SEC = (2, 5, 10)


def _edits_response_is_overload_retryable(
    status_code: int, raw_body: str, parsed_msg: str
) -> bool:
    if status_code in (429, 503):
        return True
    blob = f"{raw_body or ''} {(parsed_msg or '')}".lower()
    if "overloaded" in blob:
        return True
    if "engine is overloaded" in blob:
        return True
    return False


def _rewind_edits_multipart_files(files: list) -> None:
    """multipart 同一组 BytesIO 重发前回到文件头。"""
    for _field, tpl in files:
        if not isinstance(tpl, tuple) or len(tpl) < 2:
            continue
        bio = tpl[1]
        if isinstance(bio, io.BytesIO):
            bio.seek(0)
        elif hasattr(bio, "seek"):
            try:
                bio.seek(0)
            except Exception:
                pass


def call_openai_image_edits_api(
    payload: dict,
    ref_data_urls: list[str],
    timeout: int = 0,
) -> dict:
    """POST OFOX /v1/images/edits：multipart/form-data，文件字段 image。429/503/overloaded 自动退避重试最多 3 次；其它失败原样抛出。"""
    logger.info(
        "[route-enter] call_openai_image_edits_api model=%r ref_data_urls_count=%s",
        payload.get("model"),
        len(ref_data_urls or []),
    )

    endpoint = f"{ofox.ofox_base_url()}/images/edits"
    model = str(payload.get("model") or "")
    prompt_preview = str(payload.get("prompt") or "")
    urls = [u for u in (ref_data_urls or []) if isinstance(u, str) and u.strip()]
    att_ids = _ai_log_attachment_ids_var.get() or []
    has_attachments = bool(att_ids)
    prompt100 = (prompt_preview or "")[:100]
    n_int = max(1, int(payload.get("n") or 1))
    # Ofox Images Edit 文档建议 size=auto 保持原图尺寸；实测 1024x1024 会带来更高失败/重绘风险。
    size_s = str(payload.get("edit_size") or "auto")
    quality_s = str(payload.get("quality") or "low")

    if not timeout:
        timeout = IMAGE_EDITS_TIMEOUT_SECONDS

    logger.info(
        "[api-edit] timeout_seconds=%s model=%r endpoint=%s size=%r",
        timeout,
        model,
        endpoint,
        size_s,
    )

    file_field = _IMAGE_EDITS_MULTIPART_FILE_FIELD
    files: list[tuple[str, tuple]] = []
    for i, u in enumerate(urls[:16]):
        _, raw_bytes, mime0 = _decode_data_url_to_file_tuple(u, i)
        fname, raw_bytes, mime = _preprocess_edits_reference_bytes(raw_bytes, mime0, i)
        files.append(
            (file_field, (fname, io.BytesIO(raw_bytes), mime)),
        )

    data = {
        "model": model,
        "prompt": prompt_preview,
        "size": size_s,
        "quality": quality_s,
        "n": str(n_int),
    }

    logger.info(
        "[api-edit-multipart] phase=request request_id=%s endpoint=%s content_type=%r "
        "data_keys=%r files_field=%r files_count=%d",
        get_ai_request_id(),
        endpoint,
        "multipart/form-data (boundary set by requests on send; see response log for actual)",
        list(data.keys()),
        file_field,
        len(files),
    )

    logger.info(
        "[api-edit] phase=request request_id=%s endpoint=%s model=%s has_attachments=%s "
        "images_count=%s prompt100=%r status_code=%s success=%s error=%s",
        get_ai_request_id(),
        endpoint,
        model,
        has_attachments,
        len(files),
        prompt100,
        None,
        None,
        "",
    )
    _ai_log_req(
        "image",
        model,
        prompt_preview,
        has_image=bool(files),
        image_sizes=[_decode_data_url_bytes_size(u) for u in urls[:4]],
        provider="ofox",
    )

    headers = {
        "Authorization": f"Bearer {ofox.ofox_api_key()}",
    }

    last_status_code: object = None
    for try_idx in range(4):
        if try_idx > 0:
            wait_s = _EDITS_OVERLOAD_RETRY_WAITS_SEC[try_idx - 1]
            logger.info(
                "[api-retry] model=%r endpoint=%s status_code=%s retry_index=%s wait_seconds=%s",
                model,
                endpoint,
                last_status_code,
                try_idx,
                wait_s,
            )
            time.sleep(wait_s)

        _rewind_edits_multipart_files(files)

        try:
            resp = ofox.ofox_request(
                "POST",
                endpoint,
                headers=headers,
                data=data,
                files=files,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            err = repr(e)
            logger.info(
                "[api-edit-multipart] phase=response request_id=%s endpoint=%s content_type=%r "
                "data_keys=%r files_field=%r files_count=%d status_code=%s body=%r",
                get_ai_request_id(),
                endpoint,
                "multipart/form-data (no response; request not completed)",
                list(data.keys()),
                file_field,
                len(files),
                None,
                err[:2000],
            )
            logger.info(
                "[api-edit] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
                "images_count=%s prompt100=%r status_code=%s success=%s error=%s",
                get_ai_request_id(),
                endpoint,
                model,
                has_attachments,
                len(files),
                prompt100,
                None,
                False,
                err,
            )
            _ai_log_resp(
                "image",
                model,
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
                "[api-edit-multipart] phase=response request_id=%s endpoint=%s content_type=%r "
                "data_keys=%r files_field=%r files_count=%d status_code=%s body=%r",
                get_ai_request_id(),
                endpoint,
                "multipart/form-data (no response; request not completed)",
                list(data.keys()),
                file_field,
                len(files),
                None,
                err[:2000],
            )
            logger.info(
                "[api-edit] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
                "images_count=%s prompt100=%r status_code=%s success=%s error=%s",
                get_ai_request_id(),
                endpoint,
                model,
                has_attachments,
                len(files),
                prompt100,
                None,
                False,
                err,
            )
            _ai_log_resp(
                "image",
                model,
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

        sent_ct = _request_content_type_sent(resp)
        logger.info(
            "[api-edit-multipart] phase=response request_id=%s endpoint=%s content_type=%r "
            "data_keys=%r files_field=%r files_count=%d status_code=%s body=%r",
            get_ai_request_id(),
            endpoint,
            sent_ct or "multipart/form-data (Content-Type unavailable on response.request)",
            list(data.keys()),
            file_field,
            len(files),
            sc,
            raw_body[:2000],
        )

        if sc == 200:
            logger.info(
                "[api-edit] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
                "images_count=%s prompt100=%r status_code=%s success=%s error=%s",
                get_ai_request_id(),
                endpoint,
                model,
                has_attachments,
                len(files),
                prompt100,
                sc,
                True,
                "",
            )
            _ai_log_resp(
                "image",
                model,
                success=True,
                degraded=False,
                status_code=sc,
                error_full="",
                provider="ofox",
            )
            return resp.json()

        first_error = ofox.extract_error_message_from_response(resp)
        err = f"HTTP {sc}; parsed={first_error!r}; body={raw_body!r}"
        logger.info(
            "[api-edit] phase=response request_id=%s endpoint=%s model=%s has_attachments=%s "
            "images_count=%s prompt100=%r status_code=%s success=%s error=%s",
            get_ai_request_id(),
            endpoint,
            model,
            has_attachments,
            len(files),
            prompt100,
            sc,
            False,
            err,
        )

        if _edits_upstream_suggests_timeout(sc, raw_body, first_error):
            _ai_log_resp(
                "image",
                model,
                success=False,
                degraded=False,
                status_code=sc,
                error_full=err,
                provider="ofox",
            )
            raise RuntimeError(_edits_timeout_user_message(timeout, err))

        last_status_code = sc
        if sc == 404:
            logger.warning(
                "[api-edit] edits endpoint returned 404 model=%r. "
                "Strict image editing was not degraded to generations/reference_images because that redraws the image.",
                model,
            )
        if try_idx < 3 and _edits_response_is_overload_retryable(sc, raw_body, first_error):
            continue

        _ai_log_resp(
            "image",
            model,
            success=False,
            degraded=False,
            status_code=sc,
            error_full=err,
            provider="ofox",
        )
        raise RuntimeError(err)


def dispatch_image_request(
    model: str,
    prompt: str,
    attachment_ids: list[str],
    size: str,
    n: int,
    *,
    reference_images: Optional[list[str]] = None,
) -> dict:
    """统一分发：无图文生图；有图按 adapter 走 edits / Gemini chat，不支持则明确报错。"""
    logger.info(
        "[route-enter] dispatch_image_request model=%r attachment_ids=%r has_prebuilt_ref=%s",
        model,
        attachment_ids,
        reference_images is not None,
    )
    if reference_images is not None:
        ref = list(reference_images)[:4]
    else:
        ref = build_image_reference_data_urls(list(attachment_ids or []))

    meta = image_route_meta(model)
    logger.info(
        "[image-dispatch] model=%r adapter=%r capability=%r supports_image_to_image=%s "
        "attachment_ids=%r reference_images_count=%s",
        model,
        meta.get("adapter"),
        meta.get("capability"),
        meta.get("supports_image_to_image"),
        attachment_ids,
        len(ref),
    )

    payload = {
        "model": model,
        "prompt": (prompt or "").strip(),
        "n": max(1, int(n or 1)),
        "size": size or "1024x1024",
    }

    if not ref:
        ep = f"{ofox.ofox_base_url()}/images/generations"
        logger.info("[image-adapter] branch=text_to_image endpoint=%s", ep)
        return call_openai_image_generation_api(payload, [])

    if not meta.get("supports_image_to_image"):
        logger.info(
            "[image-adapter] branch=rejected_refs adapter=%r model=%r",
            meta.get("adapter"),
            model,
        )
        raise RuntimeError(
            "当前模型暂未确认支持 Ofox 图生图，请更换支持参考图的模型"
        )

    adapter = meta.get("adapter")
    if adapter == "openai_images":
        ep = f"{ofox.ofox_base_url()}/images/edits"
        logger.info(
            "[image-adapter] branch=openai_image_edits endpoint=%s ref_count=%s",
            ep,
            len(ref),
        )
        model_l = model.strip().lower()
        if not (model_l.startswith("azure-openai/") or model_l in _OPENAI_IMAGE_EDIT_MODELS):
            raise RuntimeError(
                f"当前 Ofox 图片编辑端点未确认支持 {model} 的图生图/图片编辑，请切换到 GPT Image 2 或 Nano Banana。"
            )
        return call_openai_image_edits_api(payload, ref)

    if adapter == "gemini_native":
        from app.services import gemini_image_service

        ep = gemini_native_generate_content_endpoint(model)
        logger.info(
            "[image-adapter] branch=gemini_native_multimodal endpoint=%s ref_count=%s",
            ep,
            len(ref),
        )
        return gemini_image_service.call_gemini_native_image_api(
            model, payload["prompt"], ref
        )

    if adapter == "seedream_native":
        ep = f"{ofox.ofox_base_url()}/images/generations"
        logger.info(
            "[image-adapter] branch=seedream_native_reference endpoint=%s ref_count=%s",
            ep,
            len(ref),
        )
        return call_seedream_image_generation_api(payload, ref)

    logger.info("[image-adapter] branch=rejected adapter=%r model=%r", adapter, model)
    raise RuntimeError(
        "当前模型暂未确认支持 Ofox 图生图，请更换支持参考图的模型"
    )


def dispatch_ai_request(
    model: str,
    prompt: str,
    attachment_ids: list[str],
    size: str,
    n: int,
    *,
    reference_images: Optional[list[str]] = None,
) -> dict:
    """兼容旧名，等同 dispatch_image_request。"""
    return dispatch_image_request(
        model, prompt, attachment_ids, size, n, reference_images=reference_images
    )


call_image_generation_api = call_openai_image_generation_api
call_image_edits_api = call_openai_image_edits_api
