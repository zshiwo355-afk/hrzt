"""阿里云 OSS：JSON 读写（聊天记录、任务快照等）。"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from app.config import (
    OSS_ACCESS_KEY_ID,
    OSS_ACCESS_KEY_SECRET,
    OSS_BUCKET,
    OSS_ENDPOINT,
    oss_configured,
)
from app.logging_config import logger

_bucket = None
_lock = threading.Lock()


def _make_bucket():
    if not oss_configured():
        raise RuntimeError("OSS 未配置完整，无法使用对象存储。")
    import oss2  # noqa: PLC0415

    auth = oss2.Auth(OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, OSS_ENDPOINT, OSS_BUCKET)


def get_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket
    with _lock:
        if _bucket is None:
            _bucket = _make_bucket()
    return _bucket


def read_json(key: str) -> Optional[Any]:
    if not oss_configured():
        return None
    try:
        import oss2.exceptions  # noqa: PLC0415

        b = get_bucket()
        r = b.get_object(key)
        raw = r.read()
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        name = type(e).__name__
        if "NoSuchKey" in name or "404" in str(e):
            return None
        logger.warning("[oss] read_json key=%s err=%s", key, repr(e))
        return None


def write_json(key: str, data: Any) -> bool:
    if not oss_configured():
        return False
    try:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        get_bucket().put_object(key, body, headers={"Content-Type": "application/json; charset=utf-8"})
        logger.info("[oss] write_json ok bucket=%s key=%s", OSS_BUCKET, key)
        return True
    except Exception as e:
        logger.warning("[oss] write_json key=%s err=%s", key, repr(e))
        return False


def write_bytes(key: str, data: bytes, *, content_type: str = "application/octet-stream") -> bool:
    if not oss_configured():
        return False
    try:
        get_bucket().put_object(
            key,
            data or b"",
            headers={"Content-Type": content_type or "application/octet-stream"},
        )
        logger.info("[oss] write_bytes ok bucket=%s key=%s size=%s", OSS_BUCKET, key, len(data or b""))
        return True
    except Exception as e:
        logger.warning("[oss] write_bytes key=%s err=%s", key, repr(e))
        return False


def read_bytes(key: str) -> Optional[bytes]:
    if not oss_configured():
        return None
    try:
        r = get_bucket().get_object(key)
        return r.read()
    except Exception as e:
        name = type(e).__name__
        if "NoSuchKey" in name or "404" in str(e):
            return None
        logger.warning("[oss] read_bytes key=%s err=%s", key, repr(e))
        return None


def delete_object(key: str) -> bool:
    if not oss_configured():
        return False
    try:
        get_bucket().delete_object(key)
        return True
    except Exception as e:
        logger.warning("[oss] delete_object key=%s err=%s", key, repr(e))
        return False


def object_exists(key: str) -> bool:
    if not oss_configured():
        return False
    try:
        get_bucket().head_object(key)
        return True
    except Exception:
        return False
