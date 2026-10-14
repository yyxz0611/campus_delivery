"""FastAPI 应用入口：装配路由、静态资源、数据库初始化。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import SessionLocal, init_db
from .redis_client import redis_client
from .routers import anomalies, auth, balance, dispatch, notifications, orders, photos, tracking
from .routers import admin as admin_router
from .services import auth_service

app = FastAPI(title=settings.app_name, version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


def _init_builtin_admin() -> None:
    db = SessionLocal()
    try:
        auth_service.ensure_builtin_admin(db, settings.admin_phone, settings.admin_initial_password)
    finally:
        db.close()


_init_builtin_admin()

app.include_router(orders.router)
app.include_router(auth.router)
app.include_router(tracking.router)
app.include_router(photos.router)
app.include_router(anomalies.router)
app.include_router(dispatch.router)
app.include_router(notifications.router)
app.include_router(admin_router.router)
app.include_router(balance.router)

# 照片等静态资源（本地存储；生产可切换 OBS）
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


@app.get("/api/meta")
def meta():
    """云服务与运行状态（体现华为云产品价值）。"""
    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        db_backend = "sqlite (本地演示)"
    elif "mysql" in db_url:
        db_backend = "华为云 RDS MySQL"
    elif "postgresql" in db_url:
        db_backend = "华为云 RDS PostgreSQL"
    else:
        db_backend = db_url.split("://")[0]

    return {
        "app": settings.app_name,
        "version": settings.version,
        "database": db_backend,
        "redis": "华为云 DCS Redis" if redis_client.mode == "redis" else "进程内缓存（未接入 DCS）",
        "redis_mode": redis_client.mode,
        "huawei_ocr": "已启用" if settings.huawei_ocr_enabled else "未启用（本地质量审核）",
    }


@app.get("/health")
def health():
    return {"status": "ok", "redis": redis_client.mode}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(settings.frontend_dir / "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/app.js", include_in_schema=False)
def app_js():
    return FileResponse(
        str(settings.frontend_dir / "app.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/style.css", include_in_schema=False)
def style_css():
    return FileResponse(
        str(settings.frontend_dir / "style.css"),
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/vue.global.prod.js", include_in_schema=False)
def vue_js():
    return FileResponse(str(settings.frontend_dir / "vue.global.prod.js"), media_type="application/javascript")