# -*- coding: utf-8 -*-
"""AI 助手路由：入口为自然语言聊天，内部走 LangGraph Supervisor 调度业务子 Agent。

鉴权复用 2.0 HMAC token（X-Auth-Token 头）；工具调用在注入的登录身份权限范围内执行。
异常策略：任何内部错误都降级为一条友好回复（HTTP 200），不再把 500 抛给前端，
同时用日志记录真实原因，便于本地排查。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agents.context import reset_context, set_context
from ..agents.graph import get_graph
from ..agents.text_utils import strip_think
from ..config import settings
from ..database import get_db
from ..security import parse_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

FALLBACK_REPLY = "抱歉，我暂时无法处理这个问题。请问您是遇到了外卖配送相关的问题吗（例如外卖丢失、未配送到寝）？"


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    thread_id: str


def _extract_reply(messages: list) -> str:
    """取本轮最后一条有内容的 AI 回复（剥离推理模型的 <think> 思考块）。"""
    message_types = ("ai", "assistant")
    for m in reversed(messages or []):
        if getattr(m, "type", None) in message_types:
            content = getattr(m, "content", "")
            if isinstance(content, str):
                text = strip_think(content)
                if text:
                    return text
            elif isinstance(content, list):
                text = strip_think(
                    "".join(b.get("text", "") for b in content if isinstance(b, dict))
                )
                if text:
                    return text
    return FALLBACK_REPLY


def resolve_thread_id(current: tuple[int, str], requested: str | None) -> str:
    """按「登录身份 + 角色」隔离会话。

    每个人每个角色是一条独立会话：同一 user_id 用不同角色登录 = 不同 thread。
    前端可以带 thread_id 后缀来「新建会话」，但前缀必须匹配当前身份，
    否则一律回落到默认会话，防止越权读取他人会话。
    """
    uid, role = current
    prefix = f"{uid}_{role}"
    if requested and requested.startswith(prefix):
        return requested
    return prefix


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if current is None:
        raise HTTPException(401, "请先登录后再使用 AI 助手")
    if not settings.minimax_enabled:
        raise HTTPException(503, "AI 助手未配置，请先设置 MINIMAX_API_KEY")

    thread_id = resolve_thread_id(current, payload.thread_id)
    tokens = set_context(db, current)
    try:
        result = get_graph().invoke(
            {
                "messages": [("user", payload.message)],
                # 每轮重置路由状态，保证多轮对话中每轮都能重新路由
                "next": "FINISH",
                "reply": "",
                "routed": False,
            },
            config={"configurable": {"thread_id": thread_id}},
        )
        reply = _extract_reply(result.get("messages", []))
        return ChatResponse(reply=reply, thread_id=thread_id)
    except Exception as e:  # noqa: BLE001 统一兜底，避免把内部堆栈暴露给前端
        logger.exception("AI 助手处理失败: %s", e)
        return ChatResponse(
            reply=f"抱歉，我这边处理时出了点问题（{e}）。请稍后重试，或把具体订单号和问题描述发给我，我再帮您跟进。",
            thread_id=thread_id,
        )
    finally:
        reset_context(tokens)