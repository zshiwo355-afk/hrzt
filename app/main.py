"""
怀仁 AI 中台：FastAPI 入口（仅应用装配、中间件、路由注册、生命周期）。
业务见 app/services，上游 HTTP 见 app/providers，配置见 app/config。
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 支持在项目根执行 `python app/main.py`：此时默认 sys.path 不含仓库根，无法 `import app.*`
if __package__ in (None, ""):
    _repo_root = Path(__file__).resolve().parent.parent
    _root_s = str(_repo_root)
    if _root_s not in sys.path:
        sys.path.insert(0, _root_s)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import APP_SESSION_SECRET, STATIC_DIR
from app.db import init_db
from app.logging_config import logger
from app.routers import (
    attachment_routes,
    auth_routes,
    chat_routes,
    client_state_routes,
    conversation_routes,
    history_routes,
    model_routes,
    root_routes,
    task_routes,
    upload_routes,
)
from app.services.task_service import ensure_task_worker_started


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[startup-log-check] app logger is working")
    init_db()
    ensure_task_worker_started()
    yield


app = FastAPI(title="怀仁AI中台", lifespan=lifespan)

_static_dir = STATIC_DIR.resolve()
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SESSION_SECRET,
    same_site="lax",
    max_age=60 * 60 * 12,
)

app.include_router(root_routes.router)
app.include_router(auth_routes.router)
app.include_router(conversation_routes.router)
app.include_router(model_routes.router)
app.include_router(upload_routes.router)
app.include_router(attachment_routes.router)
app.include_router(client_state_routes.router)
app.include_router(history_routes.router)
app.include_router(chat_routes.router)
app.include_router(task_routes.router)


if __name__ == "__main__":
    import uvicorn

    _host = os.getenv("HOST", "127.0.0.1")
    _port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=_host, port=_port)
