"""静态首页。"""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.config import (
    BASE_DIR,
    OSS_ACCESS_KEY_ID,
    OSS_ACCESS_KEY_SECRET,
    OSS_BUCKET,
    OSS_ENDPOINT,
    STATIC_DIR,
    oss_configured,
)

router = APIRouter(tags=["root"])


@router.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/health/config")
def health_config():
    """
    运行时配置自检（不返回任何密钥，仅用于排查「.env 有但线上不生效」）。
    注意：配置在进程 import app 时读入，改 .env 后必须重启服务才生效。
    """
    env_path = BASE_DIR / ".env"
    return {
        "env_file_path": str(env_path),
        "env_file_exists": env_path.is_file(),
        "base_dir": str(BASE_DIR),
        "oss_configured": oss_configured(),
        "oss_env_present": {
            "OSS_ACCESS_KEY_ID": bool(OSS_ACCESS_KEY_ID),
            "OSS_ACCESS_KEY_SECRET": bool(OSS_ACCESS_KEY_SECRET),
            "OSS_ENDPOINT": bool(OSS_ENDPOINT),
            "OSS_BUCKET": bool(OSS_BUCKET),
        },
        "ofox_key_present": bool(os.getenv("OFOX_API_KEY")),
        "hint": "若 oss_configured 为 false，说明当前进程启动时未读到完整 OSS 四项；请确认 env_file_exists、部署目录是否为仓库根，以及修改 .env 后是否已重启进程。",
    }
