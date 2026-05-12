"""应用日志初始化（单例 logger：huairen）。"""
from __future__ import annotations

import logging
import os

_LOG_FMT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


def setup_logging() -> logging.Logger:
    try:
        logging.basicConfig(level=logging.INFO, format=_LOG_FMT, force=True)
    except TypeError:
        logging.basicConfig(level=logging.INFO, format=_LOG_FMT)

    logger = logging.getLogger("huairen")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        stream = logging.StreamHandler()
        stream.setLevel(logging.INFO)
        stream.setFormatter(logging.Formatter(_LOG_FMT))
        logger.addHandler(stream)
    logger.propagate = False

    has_http = bool((os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or "").strip())
    has_https = bool((os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip())
    from app.config import _is_ofox_proxy_disabled

    logger.info(
        "[ofox] OFOX HTTP via Session(trust_env=False)+explicit proxies=None; "
        "OFOX_DISABLE_PROXY raw=%r legacy_flag=%s; env HTTP_PROXY/http=%s HTTPS_PROXY/https=%s",
        os.getenv("OFOX_DISABLE_PROXY"),
        _is_ofox_proxy_disabled(),
        has_http,
        has_https,
    )
    return logger


logger = setup_logging()
