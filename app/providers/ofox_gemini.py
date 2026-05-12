"""Ofox 上 Gemini Native：generateContent（非 OpenAI chat/completions）。"""
from __future__ import annotations

from urllib.parse import quote, urlparse

from app.config import OFOX_BASE_URL


def gemini_native_generate_content_endpoint(model: str) -> str:
    """
    POST …/gemini/v1beta/models/{model}:generateContent
    model 含 publisher 路径（如 google/gemini-3-pro-image-preview）时对整段做 path 安全编码。
    """
    raw = (OFOX_BASE_URL or "").strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("invalid OFOX_BASE_URL for Gemini Native URL")
    root = f"{parsed.scheme}://{parsed.netloc}"
    m = (model or "").strip()
    enc = quote(m, safe="")
    return f"{root}/gemini/v1beta/models/{enc}:generateContent"


def gemini_native_stream_generate_content_endpoint(model: str) -> str:
    """
    POST …/gemini/v1beta/models/{model}:streamGenerateContent
    model 含 publisher 路径时对整段做 path 安全编码。
    """
    raw = (OFOX_BASE_URL or "").strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("invalid OFOX_BASE_URL for Gemini Native URL")
    root = f"{parsed.scheme}://{parsed.netloc}"
    m = (model or "").strip()
    enc = quote(m, safe="")
    return f"{root}/gemini/v1beta/models/{enc}:streamGenerateContent"
