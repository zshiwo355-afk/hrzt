"""文本模型能力目录与 reasoning/provider 映射。"""
from __future__ import annotations

from typing import Any

REASONING_MODE_DEFAULT = "default"
REASONING_MODE_INSTANT = "instant"
REASONING_MODE_THINKING = "thinking"
REASONING_MODE_ADVANCED = "advanced"
REASONING_MODE_ORDER = (
    REASONING_MODE_DEFAULT,
    REASONING_MODE_INSTANT,
    REASONING_MODE_THINKING,
    REASONING_MODE_ADVANCED,
)

TEXT_MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "label": "GPT 5.4",
        "canonical_id": "openai/gpt-5.4",
        "hint": "通用对话、稳定输出、日常任务",
        "provider": "openai",
        "tokens": ("gpt", "5.4"),
        "supports_reasoning": True,
        "reasoning_modes": REASONING_MODE_ORDER,
    },
    {
        "label": "GPT 5.5",
        "canonical_id": "openai/gpt-5.5",
        "hint": "复杂推理、代码生成、长内容处理",
        "provider": "openai",
        "tokens": ("gpt", "5.5"),
        "supports_reasoning": True,
        "reasoning_modes": REASONING_MODE_ORDER,
    },
    {
        "label": "Gemini 3.1 Pro Preview",
        "canonical_id": "google/gemini-3.1-pro-preview",
        "hint": "长上下文理解、多文档整合、信息归纳",
        "provider": "google",
        "tokens": ("gemini", "3.1", "pro", "preview"),
        "supports_reasoning": True,
        "reasoning_modes": REASONING_MODE_ORDER,
    },
    {
        "label": "Claude Opus 4.7",
        "canonical_id": "anthropic/claude-opus-4.7",
        "hint": "高质量写作、总结润色、复杂表达",
        "provider": "anthropic",
        "tokens": ("opus", "4.7"),
        "supports_reasoning": True,
        "reasoning_modes": REASONING_MODE_ORDER,
        "native_model": "claude-opus-4-7",
    },
)

_TEXT_MODEL_BY_ID = {
    str(item["canonical_id"]): dict(item)
    for item in TEXT_MODEL_CATALOG
}


def text_model_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in TEXT_MODEL_CATALOG]


def known_text_model_ids() -> list[str]:
    return [str(item["canonical_id"]) for item in TEXT_MODEL_CATALOG]


def get_text_model_capability(model_id: str) -> dict[str, Any]:
    return dict(_TEXT_MODEL_BY_ID.get(str(model_id or "").strip(), {}))


def model_provider(model_id: str) -> str:
    mid = str(model_id or "").strip().lower()
    if mid.startswith("openai/"):
        return "openai"
    if mid.startswith("google/"):
        return "google"
    if mid.startswith("anthropic/"):
        return "anthropic"
    cap = get_text_model_capability(model_id)
    return str(cap.get("provider") or "unknown")


def model_native_id(model_id: str) -> str:
    cap = get_text_model_capability(model_id)
    native = str(cap.get("native_model") or "").strip()
    if native:
        return native
    return str(model_id or "").strip()


def normalize_reasoning_mode(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in REASONING_MODE_ORDER else REASONING_MODE_DEFAULT


def upstream_supports_parameter(supported_parameters: Any, *names: str) -> bool:
    wanted = {str(name or "").strip().lower() for name in names if str(name or "").strip()}
    if not wanted:
        return False
    if isinstance(supported_parameters, dict):
        for key, value in supported_parameters.items():
            key_l = str(key or "").strip().lower()
            if key_l in wanted:
                return bool(value) if isinstance(value, bool) else True
    if isinstance(supported_parameters, (list, tuple, set)):
        for item in supported_parameters:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("id") or item.get("key") or "").strip().lower()
                if name in wanted:
                    enabled = item.get("enabled")
                    if enabled is None:
                        return True
                    return bool(enabled)
            else:
                if str(item or "").strip().lower() in wanted:
                    return True
    if isinstance(supported_parameters, str):
        return supported_parameters.strip().lower() in wanted
    return False


def supports_reasoning_for_model(model_id: str, supported_parameters: Any = None) -> bool:
    cap = get_text_model_capability(model_id)
    fallback = bool(cap.get("supports_reasoning"))
    if supported_parameters is None:
        return fallback
    return upstream_supports_parameter(
        supported_parameters,
        "reasoning",
        "reasoning_effort",
        "thinking",
        "effort",
    ) or fallback


def reasoning_modes_for_model(model_id: str, supported_parameters: Any = None) -> list[str]:
    if not supports_reasoning_for_model(model_id, supported_parameters=supported_parameters):
        return []
    cap = get_text_model_capability(model_id)
    modes = cap.get("reasoning_modes") or REASONING_MODE_ORDER
    return [mode for mode in modes if mode in REASONING_MODE_ORDER]


def enrich_text_model_row(row: dict[str, Any], *, supported_parameters: Any = None) -> dict[str, Any]:
    model_id = str(row.get("id") or "")
    cap = get_text_model_capability(model_id)
    provider = str(cap.get("provider") or model_provider(model_id))
    supports_reasoning = supports_reasoning_for_model(
        model_id,
        supported_parameters=supported_parameters,
    )
    reasoning_modes = reasoning_modes_for_model(
        model_id,
        supported_parameters=supported_parameters,
    )
    return {
        **row,
        "provider": provider,
        "supports_reasoning": supports_reasoning,
        "reasoning_modes": reasoning_modes,
        "reasoning_default_mode": REASONING_MODE_DEFAULT if supports_reasoning else "",
    }


def build_text_request_adapter(model_id: str, reasoning_mode: str | None) -> dict[str, Any]:
    normalized_mode = normalize_reasoning_mode(reasoning_mode)
    provider = model_provider(model_id)
    supports_reasoning = supports_reasoning_for_model(model_id)

    spec: dict[str, Any] = {
        "provider": provider,
        "transport": "ofox_openai_compat",
        "effective_model": str(model_id or "").strip(),
        "effective_reasoning_mode": normalized_mode,
        "supports_reasoning": supports_reasoning,
        "chat_completions_extra": {},
        "anthropic_extra": {},
    }
    if not supports_reasoning:
        spec["effective_reasoning_mode"] = REASONING_MODE_DEFAULT
        return spec

    if provider == "openai":
        mapping = {
            REASONING_MODE_DEFAULT: None,
            REASONING_MODE_INSTANT: "low",
            REASONING_MODE_THINKING: "high",
            REASONING_MODE_ADVANCED: "xhigh",
        }
        effort = mapping.get(normalized_mode)
        if effort:
            spec["chat_completions_extra"] = {"reasoning_effort": effort}
        return spec

    if provider == "google":
        mapping = {
            REASONING_MODE_DEFAULT: None,
            REASONING_MODE_INSTANT: "low",
            REASONING_MODE_THINKING: "medium",
            REASONING_MODE_ADVANCED: "high",
        }
        effort = mapping.get(normalized_mode)
        if effort:
            spec["chat_completions_extra"] = {"reasoning_effort": effort}
        return spec

    if provider == "anthropic":
        spec["transport"] = "ofox_anthropic_native"
        spec["effective_model"] = model_native_id(model_id)
        effort_mapping = {
            REASONING_MODE_DEFAULT: "",
            REASONING_MODE_INSTANT: "low",
            REASONING_MODE_THINKING: "high",
            REASONING_MODE_ADVANCED: "xhigh",
        }
        effort = effort_mapping.get(normalized_mode, "")
        anthropic_extra: dict[str, Any] = {
            "thinking": {"type": "adaptive"},
        }
        if effort:
            anthropic_extra["output_config"] = {"effort": effort}
        spec["anthropic_extra"] = anthropic_extra
        return spec

    spec["effective_reasoning_mode"] = REASONING_MODE_DEFAULT
    return spec
