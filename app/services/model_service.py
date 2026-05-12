"""上游模型列表分类（仅用于 GET /api/models 展示分组）。"""
from __future__ import annotations

import re
import time

from fastapi import HTTPException

from app.ai_context import (
    _ai_log_req,
    _ai_log_resp,
    reset_ai_request_context,
    set_ai_request_context,
)
from app.logging_config import logger
from app.providers import ofox
from app.services import model_capability_service

TEXT_MODEL_TARGETS = tuple(model_capability_service.text_model_catalog())

_resolved_text_model_ids_cache: tuple[str, ...] = tuple(
    target["canonical_id"] for target in TEXT_MODEL_TARGETS
)
_resolved_image_model_ids_cache: tuple[str, ...] = ()
_models_catalog_cache: dict | None = None
_models_catalog_cache_at = 0.0
_MODELS_CATALOG_CACHE_TTL_SECONDS = 300


def _text_model_blob(model_id: str, model_name: str = "") -> str:
    return f"{model_id} {model_name}".strip().lower()


def _matches_text_target(model_id: str, model_name: str, target: dict) -> bool:
    blob = _text_model_blob(model_id, model_name)
    if not blob:
        return False
    if model_id == target["canonical_id"]:
        return True
    return all(token in blob for token in target["tokens"])


def _resolve_text_catalog_rows(rows: list[dict]) -> list[dict]:
    picked: list[dict] = []
    used_ids: set[str] = set()
    for target in TEXT_MODEL_TARGETS:
        match = next(
            (
                row
                for row in rows
                if str(row.get("id") or "") not in used_ids
                and _matches_text_target(
                    str(row.get("id") or ""),
                    str(row.get("name") or ""),
                    target,
                )
            ),
            None,
        )
        if not match:
            continue
        cloned = dict(match)
        cloned["name"] = target["label"]
        cloned["hint"] = target["hint"]
        picked.append(cloned)
        used_ids.add(str(match.get("id") or ""))
    return picked


def resolved_text_model_ids() -> list[str]:
    return list(_resolved_text_model_ids_cache)


def resolved_image_model_ids() -> list[str]:
    return list(_resolved_image_model_ids_cache)


def is_model_allowed(model_id: str, *, mode: str | None = None) -> bool:
    mid = (model_id or "").strip()
    if not mid:
        return False
    if mode == "video":
        return False
    if mode == "image":
        image_ids = set(resolved_image_model_ids())
        if mid in image_ids:
            return True
        return _name_id_imply_image(mid.lower(), mid.lower())
    allowed_ids = set(resolved_text_model_ids())
    if mid in allowed_ids:
        return True
    return any(_matches_text_target(mid, "", target) for target in TEXT_MODEL_TARGETS)


def ensure_model_allowed(model_id: str, *, mode: str | None = None) -> None:
    if mode == "video":
        raise HTTPException(status_code=400, detail="video disabled")
    if is_model_allowed(model_id, mode=mode):
        return
    if mode == "image":
        raise HTTPException(status_code=400, detail="当前只允许使用上游返回的图片模型。")
    raise HTTPException(status_code=400, detail="当前只允许使用 4 个指定的文本模型。")


def model_modalities(model_item: dict) -> tuple[list[str], list[str]]:
    """Normalize architecture.input_modalities / output_modalities from upstream."""
    raw_arch = model_item.get("architecture")
    arch = raw_arch if isinstance(raw_arch, dict) else {}

    def _norm_list(key: str) -> list[str]:
        val = arch.get(key)
        if not isinstance(val, list):
            return []
        out: list[str] = []
        for x in val:
            if isinstance(x, str):
                out.append(x.lower())
            elif x is not None:
                out.append(str(x).lower())
        return out

    return _norm_list("input_modalities"), _norm_list("output_modalities")


def _raw_arch_modalities(model_item: dict) -> tuple[object, object]:
    raw_arch = model_item.get("architecture")
    arch = raw_arch if isinstance(raw_arch, dict) else {}
    return arch.get("input_modalities"), arch.get("output_modalities")


def _name_id_imply_image(id_l: str, name_l: str) -> bool:
    """id/name 命中图片相关关键词（seedream、gpt-image、banana、gemini image 等）。"""
    for h in (id_l, name_l):
        if "seedream" in h:
            return True
        if "gpt-image" in h or "gpt image" in h:
            return True
        if "banana" in h:
            return True
        if "gemini image" in h:
            return True
        if re.search(r"gemini.*image", h):
            return True
        if "image-preview" in h or "image preview" in h:
            return True
        if "images" in h:
            return True
        if "image" in h:
            return True
    return False


def _name_id_imply_video(id_l: str, name_l: str) -> bool:
    return "video" in id_l or "video" in name_l


def classify_model(model_item: dict) -> str:
    """按 id/name 关键词与 architecture 模态分类；不因 output 含 text 就强制 text。"""
    mid = model_item.get("id") or ""
    label = model_item.get("name") or ""
    id_l = str(mid).lower()
    name_l = str(label).lower()

    ins_raw, outs_raw = _raw_arch_modalities(model_item)
    ins, outs = model_modalities(model_item)
    oset = set(outs)

    logger.info(
        "[model-classify-input] id=%r name=%r input_modalities=%r output_modalities=%r",
        mid,
        label,
        ins_raw,
        outs_raw,
    )

    if _name_id_imply_image(id_l, name_l):
        return "image"

    if outs and oset == {"image"}:
        return "image"

    if "image" in ins and ("image" in id_l or "image" in name_l):
        return "image"

    if _name_id_imply_video(id_l, name_l):
        return "video"

    if oset == {"video"}:
        return "video"
    if "video" in oset and "text" not in oset and "image" not in oset:
        return "video"

    if "image" in oset:
        return "image"
    if "video" in oset:
        return "video"
    return "text"


def image_route_meta(model_id: str) -> dict:
    """
    生图任务分流元数据（与 image_service.dispatch 一致）。
    adapter: openai_images | gemini_native | seedream_native | unknown | text | video
    capability: image-edit | image-gemini | image-gen-only | text | video
    """
    mid = (model_id or "").strip()
    ml = mid.lower()

    if ml.startswith("azure-openai/") or ml == "openai/gpt-image-2":
        return {
            "supports_text_to_image": True,
            "supports_image_to_image": True,
            "adapter": "openai_images",
            "capability": "image-edit",
        }

    if "seedream" in ml or (ml.startswith("volcengine/doubao") and "seedream" in ml):
        return {
            "supports_text_to_image": True,
            "supports_image_to_image": False,
            "adapter": "seedream_native",
            "capability": "image-gen-only",
        }

    if ml in {"nano-banana", "google/nano-banana", "google/gemini-2.5-flash-image-preview"}:
        return {
            "supports_text_to_image": True,
            "supports_image_to_image": True,
            "adapter": "gemini_native",
            "capability": "image-gemini",
        }

    if ml.startswith("google/") and (
        "banana" in ml
        or (
            "gemini" in ml
            and (
                "image" in ml
                or "flash-image" in ml
                or "pro-image" in ml
            )
        )
    ):
        return {
            "supports_text_to_image": True,
            "supports_image_to_image": True,
            "adapter": "gemini_native",
            "capability": "image-gemini",
        }

    return {
        "supports_text_to_image": True,
        "supports_image_to_image": False,
        "adapter": "unknown",
        "capability": "image-gen-only",
    }


def catalog_model_extensions(model_id: str, model_name: str, category: str) -> dict:
    """写入各分组与 all 的 capability / adapter / supports_* 字段。"""
    if category == "image":
        m = image_route_meta(str(model_id or ""))
        return {
            "capability": m["capability"],
            "adapter": m["adapter"],
            "supports_text_to_image": m["supports_text_to_image"],
            "supports_image_to_image": m["supports_image_to_image"],
        }
    ad = "text" if category == "text" else "video" if category == "video" else "unknown"
    return {
        "capability": category,
        "adapter": ad,
        "supports_text_to_image": category == "text",
        "supports_image_to_image": False,
    }


def fetch_models_catalog() -> dict:
    """GET /v1/models 并返回与原先一致的 JSON 结构。"""
    global _models_catalog_cache, _models_catalog_cache_at
    now = time.time()
    if (
        _models_catalog_cache is not None
        and now - _models_catalog_cache_at < _MODELS_CATALOG_CACHE_TTL_SECONDS
    ):
        return _models_catalog_cache

    rid_t, att_t, im_t = set_ai_request_context([], None)
    try:
        _ai_log_req(
            "models_list",
            "-",
            "",
            has_image=False,
            image_sizes=[],
            provider="ofox",
        )
        try:
            resp = ofox.ofox_request(
                "GET",
                f"{ofox.ofox_base_url()}/models",
                headers={"Authorization": f"Bearer {ofox.ofox_api_key()}"},
                timeout=20,
            )

            if resp.status_code != 200:
                _ai_log_resp(
                    "models_list",
                    "-",
                    success=False,
                    degraded=False,
                    status_code=resp.status_code,
                    error_full=(resp.text or "")[:4000],
                    provider="ofox",
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"获取模型列表失败，状态码: {resp.status_code}，返回: {resp.text}",
                )

            body = resp.json()
            data = body.get("data")
            if not isinstance(data, list):
                alt = body.get("models")
                data = alt if isinstance(alt, list) else []
        except HTTPException:
            raise
        except Exception as e:
            _ai_log_resp(
                "models_list",
                "-",
                success=False,
                degraded=False,
                status_code=None,
                error_full=repr(e),
                provider="ofox",
            )
            raise HTTPException(status_code=500, detail=f"获取模型列表失败: {repr(e)}")

        _ai_log_resp(
            "models_list",
            "-",
            success=True,
            degraded=False,
            status_code=resp.status_code,
            error_full="",
            provider="ofox",
        )

        global _resolved_text_model_ids_cache, _resolved_image_model_ids_cache

        text_rows: list[dict] = []
        image_rows: list[dict] = []
        upstream_video_rows: list[dict] = []
        all_rows: list[dict] = []
        upstream_model_count = 0

        for item in data:
            if not isinstance(item, dict):
                continue
            upstream_model_count += 1
            arch = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
            ins_raw = arch.get("input_modalities")
            outs_raw = arch.get("output_modalities")
            category = classify_model(item)
            logger.info(
                "[models-upstream] id=%r name=%r input_modalities=%r output_modalities=%r classify=%s",
                item.get("id"),
                item.get("name"),
                ins_raw,
                outs_raw,
                category,
            )
            mid = item.get("id")
            label = item.get("name") or mid
            name_str = label if label is not None else ""
            ext = catalog_model_extensions(str(mid or ""), name_str, category)
            row = {"id": mid, "name": name_str, **ext}
            supported_parameters = item.get("supported_parameters")
            if category == "text":
                row = model_capability_service.enrich_text_model_row(
                    row,
                    supported_parameters=supported_parameters,
                )
            rich_row = {
                "id": mid,
                "name": name_str,
                "input_modalities": ins_raw,
                "output_modalities": outs_raw,
                "classify": category,
                "supported_parameters": supported_parameters,
                **ext,
            }
            if category == "text":
                rich_row = model_capability_service.enrich_text_model_row(
                    rich_row,
                    supported_parameters=supported_parameters,
                )
            if category == "text":
                text_rows.append(row)
            elif category == "image":
                image_rows.append(row)
            elif category == "video":
                upstream_video_rows.append(row)
            all_rows.append(rich_row)

        resolved_text_rows = _resolve_text_catalog_rows(text_rows)
        _resolved_text_model_ids_cache = tuple(
            str(row.get("id") or "") for row in resolved_text_rows if row.get("id")
        )
        image_rows = sorted(image_rows, key=lambda x: (x.get("name") or "").lower())
        _resolved_image_model_ids_cache = tuple(
            str(row.get("id") or "") for row in image_rows if row.get("id")
        )
        image_ids = {str(row.get("id") or "") for row in image_rows}
        text_ids = {str(row.get("id") or "") for row in resolved_text_rows}
        result: dict[str, list] = {
            "text": resolved_text_rows,
            "image": image_rows,
            "all": [
                row
                for row in all_rows
                if str(row.get("id") or "") in text_ids or str(row.get("id") or "") in image_ids
            ],
        }

        logger.info(
            "[models-summary] upstream_models=%d text=%d image=%d upstream_video=%d all=%d "
            "text_ids=%s image_count=%d",
            upstream_model_count,
            len(result["text"]),
            len(result["image"]),
            len(upstream_video_rows),
            len(result["all"]),
            [m.get("id") for m in result["text"]],
            len(result["image"]),
        )

        _models_catalog_cache = result
        _models_catalog_cache_at = time.time()
        return result
    finally:
        reset_ai_request_context(rid_t, att_t, im_t)
