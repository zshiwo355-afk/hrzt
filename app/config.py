"""环境变量、常量与路径（启动时加载）。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOAD_META_DIR = UPLOADS_DIR / "_meta"
TASKS_DIR = UPLOADS_DIR / "_tasks"
CLIENT_STATE_DIR = UPLOADS_DIR / "_client_state"

load_dotenv(BASE_DIR / ".env")

OFOX_API_KEY = os.getenv("OFOX_API_KEY")
if not OFOX_API_KEY:
    raise RuntimeError("没有读取到 OFOX_API_KEY，请检查 .env 文件")

OFOX_BASE_URL = "https://api.ofox.ai/v1"


def _is_ofox_proxy_disabled() -> bool:
    """默认不走系统代理。OFOX_DISABLE_PROXY=0/false/no/off 时标记为允许环境代理（仅用于启动日志）。"""
    raw = (os.getenv("OFOX_DISABLE_PROXY") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "1127")

# ---------- OSS（聊天记录 / 任务快照；缺省项不强制） ----------
OSS_ACCESS_KEY_ID = (os.getenv("OSS_ACCESS_KEY_ID") or "").strip()
OSS_ACCESS_KEY_SECRET = (os.getenv("OSS_ACCESS_KEY_SECRET") or "").strip()
OSS_ENDPOINT = (os.getenv("OSS_ENDPOINT") or "").strip()
OSS_BUCKET = (os.getenv("OSS_BUCKET") or "").strip()
OSS_PUBLIC_BASE_URL = (os.getenv("OSS_PUBLIC_BASE_URL") or "").strip().rstrip("/")
OSS_DOWNLOAD_PROXY = (os.getenv("OSS_DOWNLOAD_PROXY") or "redirect").strip().lower()
# 附件上传前缀：优先 OSS_UPLOAD_PREFIX，其次 OSS_PREFIX_ATTACHMENTS
_raw_upload_prefix = (os.getenv("OSS_UPLOAD_PREFIX") or "").strip().strip("/")
if not _raw_upload_prefix:
    _raw_upload_prefix = (os.getenv("OSS_PREFIX_ATTACHMENTS") or "attachments").strip().strip("/")
OSS_UPLOAD_PREFIX = _raw_upload_prefix
OSS_PREFIX_CHAT_HISTORY = (os.getenv("OSS_PREFIX_CHAT_HISTORY") or "chat-history").strip().strip("/")
OSS_PREFIX_TASK_RESULTS = (os.getenv("OSS_PREFIX_TASK_RESULTS") or "task-results").strip().strip("/")
OSS_PREFIX_ATTACHMENTS = (os.getenv("OSS_PREFIX_ATTACHMENTS") or "attachments").strip().strip("/")
OSS_HISTORY_USER_ID = (os.getenv("OSS_HISTORY_USER_ID") or os.getenv("HISTORY_USER_ID") or "").strip()


def oss_configured() -> bool:
    return bool(OSS_ACCESS_KEY_ID and OSS_ACCESS_KEY_SECRET and OSS_ENDPOINT and OSS_BUCKET)


def stable_history_user_from_password() -> str:
    digest = hashlib.sha256(ACCESS_PASSWORD.encode("utf-8")).hexdigest()[:28]
    return f"pw_{digest}"


APP_SESSION_SECRET = os.getenv(
    "APP_SESSION_SECRET",
    "huairen-ai-session-2026-very-long-random-key-9981",
)
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "openai/gpt-5.4")

TEXT_TIMEOUT_SECONDS = int(os.getenv("TEXT_TIMEOUT_SECONDS", "180"))
SUMMARY_TIMEOUT_SECONDS = int(os.getenv("SUMMARY_TIMEOUT_SECONDS", "120"))
RAG_BASE_URL = (os.getenv("RAG_BASE_URL") or "http://121.43.112.129:3001").strip().rstrip("/")
RAG_SEARCH_TIMEOUT_SECONDS = int(os.getenv("RAG_SEARCH_TIMEOUT_SECONDS", "12"))
RAG_DEFAULT_TOP_K = int(os.getenv("RAG_DEFAULT_TOP_K", "10"))
RAG_CONTEXT_MAX_ITEMS = int(os.getenv("RAG_CONTEXT_MAX_ITEMS", "5"))
WEB_SEARCH_BASE_URL = (os.getenv("WEB_SEARCH_BASE_URL") or "").strip().rstrip("/")
WEB_SEARCH_PATH = (os.getenv("WEB_SEARCH_PATH") or "/search").strip()
if WEB_SEARCH_PATH and not WEB_SEARCH_PATH.startswith("/"):
    WEB_SEARCH_PATH = "/" + WEB_SEARCH_PATH
WEB_SEARCH_API_KEY = (os.getenv("WEB_SEARCH_API_KEY") or "").strip()
WEB_SEARCH_API_KEY_HEADER = (os.getenv("WEB_SEARCH_API_KEY_HEADER") or "Authorization").strip()
WEB_SEARCH_API_KEY_PREFIX = os.getenv("WEB_SEARCH_API_KEY_PREFIX", "Bearer ")
WEB_SEARCH_TIMEOUT_SECONDS = int(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "12"))
WEB_SEARCH_TOP_K = int(os.getenv("WEB_SEARCH_TOP_K", "5"))
WEB_SEARCH_CONTEXT_MAX_ITEMS = int(os.getenv("WEB_SEARCH_CONTEXT_MAX_ITEMS", "3"))


def web_search_configured() -> bool:
    return bool(WEB_SEARCH_BASE_URL)

# WebSocket 在等待上游首包期间定期推帧，避免 Nginx 等默认 ~60s 读空闲超时断开
WS_KEEPALIVE_SECONDS = float(os.getenv("WS_KEEPALIVE_SECONDS", "20"))
IMAGE_TASK_TIMEOUT_SECONDS = int(os.getenv("IMAGE_TASK_TIMEOUT_SECONDS", "1800"))
IMAGE_EDITS_TIMEOUT_SECONDS = int(os.getenv("IMAGE_EDITS_TIMEOUT_SECONDS", "500"))
TASK_POLL_INTERVAL_SECONDS = float(os.getenv("TASK_POLL_INTERVAL_SECONDS", "1.5"))
TASK_WORKER_CONCURRENCY = max(1, int(os.getenv("TASK_WORKER_CONCURRENCY", "4")))
TASK_RUNNING_REQUEUE_SECONDS = max(60, int(os.getenv("TASK_RUNNING_REQUEUE_SECONDS", "3600")))
DB_POOL_SIZE = max(1, int(os.getenv("DB_POOL_SIZE", "30")))
DB_MAX_OVERFLOW = max(0, int(os.getenv("DB_MAX_OVERFLOW", "60")))
DB_POOL_TIMEOUT_SECONDS = max(1, int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")))

DEFAULT_TEXT_SYSTEM_PROMPT = (
    "你是怀仁AI中台的企业内部助手。"
    "请直接给出清晰、简洁、可执行的中文回答。"
    "不要展示思考过程，不要输出分析步骤，不要自言自语，"
    "不要使用“我来一步一步分析”“下面我先想一下”“我的思路是”这类过渡废话。"
)

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".txt",
    ".md",
    ".xlsx",
    ".xls",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


def ensure_data_directories() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_META_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_STATE_DIR.mkdir(parents=True, exist_ok=True)


ensure_data_directories()
