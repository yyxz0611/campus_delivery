"""数据库引擎与会话管理（SQLAlchemy 2.0 同步 API）。

本地默认 SQLite，生产通过 DATABASE_URL 切换华为云 RDS（MySQL/PostgreSQL）。
SQLite 需要 check_same_thread=False 以配合 FastAPI 线程池。
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """建表（幂等）。"""
    from . import models  # noqa: F401 确保模型已注册

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()