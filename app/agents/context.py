# -*- coding: utf-8 -*-
"""Agent 请求上下文：用 contextvars 在同步调用链中传递 db session 与当前登录用户。

工具函数通过 get_db() / get_current_user() 读取当前请求上下文，
从而在 LLM 工具调用时仍能复用 FastAPI 注入的会话与登录身份（权限安全的关键）。
"""
from __future__ import annotations

import contextvars

from sqlalchemy.orm import Session

_db_var: contextvars.ContextVar[Session | None] = contextvars.ContextVar("agent_db", default=None)
_current_user_var: contextvars.ContextVar[tuple[int, str] | None] = contextvars.ContextVar(
    "agent_current_user", default=None
)


def set_context(db: Session, current_user: tuple[int, str] | None) -> tuple:
    """设置当前请求上下文，返回 token 供 reset_context 还原。"""
    return (_db_var.set(db), _current_user_var.set(current_user))


def reset_context(tokens: tuple) -> None:
    """还原上下文（请求结束时调用）。"""
    _db_var.reset(tokens[0])
    _current_user_var.reset(tokens[1])


def get_db() -> Session:
    db = _db_var.get()
    if db is None:
        raise RuntimeError("Agent 上下文未初始化：请在 assistant 路由中先 set_context")
    return db


def get_current_user() -> tuple[int, str] | None:
    return _current_user_var.get()