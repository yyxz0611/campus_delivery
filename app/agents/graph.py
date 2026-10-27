# -*- coding: utf-8 -*-
"""LangGraph Supervisor 图：主调度 -> 业务子 Agent -> 回主调度 -> ... -> FINISH。

路由采用三级降级，保证任何模型表现都能得到回复、绝不抛错：
    1) function calling（MiniMax 已验证支持 tool_calls）→ 直接取 next/reply
    2) 模型输出 JSON 文本 → 本地解析（兼容 <think> 思考块与代码块包裹）
    3) 关键词规则兜底 → 命中配送异常关键词交给 anomaly_agent，否则 FINISH

早期版本直接 `response["next"]` 取 function calling 结果，当模型在某些输入下
没有返回 tool_calls 时，langchain 的 parser 会给出 None，进而抛
TypeError: 'NoneType' object is not subscriptable（前端表现为 500）。现在所有取值
都做了 None 保护，并补齐了"模型没给回复"时的兜底文案。

checkpoint 说明：
- 当前用 MemorySaver（进程内多轮记忆，按 thread_id 隔离会话，重启后丢失）。
- 生产切华为云 DCS Redis 时，将 build_graph 中的 checkpointer 替换为
  langgraph.checkpoint.redis.RedisSaver（基于 settings.redis_url），即可持久化多轮对话。
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from .agents.anomaly_agent import build_anomaly_agent
from .llm import get_llm
from .prompts import SUPERVISOR_PROMPT
from .text_utils import loads_first_json, strip_think
from ..config import settings


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    next: str
    reply: str
    routed: bool


class Router(BaseModel):
    """主调度的路由决策（function calling 的工具 schema）。"""

    next: Literal["anomaly_agent", "FINISH"] = Field(
        description="下一个要处理本轮请求的子 Agent；无需子 Agent 时填 FINISH"
    )
    reply: str = Field(
        default="",
        description="给用户看的一句话中文回复，简洁友好即可",
    )


VALID_ROUTES = ("anomaly_agent", "FINISH")

# 关键词兜底：命中即认为属于配送异常，交给 anomaly_agent
ANOMALY_KEYWORDS = (
    "丢失", "丢单", "丢了", "丢件", "不见", "没收到", "未收到", "没有收到", "没送到",
    "未送达", "没送达", "未送到", "没送", "未送", "送错", "送错楼", "送错楼栋",
    "异常", "投诉", "餐品", "洒了", "餐洒", "凉了", "漏餐", "错餐", "缺餐", "坏掉",
    # 通知类请求
    "通知", "发消息", "发个消息", "发信息", "联系管理员", "联系骑手", "联系学生",
    "告诉管理员", "转告", "催一下", "催单", "催个单", "发个通知", "留言",
)

DEFAULT_FINISH_REPLY = (
    "抱歉，我是「校园外卖配送对接平台」的 AI 助手，目前主要帮您处理配送相关的问题"
    "（例如外卖丢失、未配送到寝、错送）。可以把具体订单号和遇到的情况告诉我，我来帮您跟进。"
)

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_NEXT_FIELD_RE = re.compile(r'"next"\s*:\s*"([A-Za-z_]+)"')


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return "" if content is None else str(content)


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if getattr(m, "type", None) == "human":
            return _content_to_text(getattr(m, "content", ""))
    return ""


def _answered_this_turn(messages: list) -> bool:
    """本轮（最后一条用户消息之后）是否已经有 AI 回复。"""
    idx = -1
    for i in range(len(messages or []) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "human":
            idx = i
            break
    return any(getattr(m, "type", None) in ("ai", "assistant") for m in (messages or [])[idx + 1:])


def _as_dict(parsed) -> dict:
    """把结构化输出（dict 或 Pydantic 实例）统一成 dict。"""
    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        return parsed
    dump = getattr(parsed, "model_dump", None)
    if callable(dump):
        try:
            return dump()
        except Exception:
            return {}
    return {}


def _normalize_route(value) -> str | None:
    if not isinstance(value, str):
        return None
    route = value.strip()
    if route in VALID_ROUTES:
        return route
    lowered = route.lower()
    for valid in VALID_ROUTES:
        if valid.lower() == lowered:
            return valid
    if "anomaly" in lowered:
        return "anomaly_agent"
    return "FINISH"


def _parse_supervisor_output(content: str) -> tuple[str | None, str]:
    """解析 supervisor 的 JSON 输出，返回 (next, reply)；无法解析时 next 为 None。"""
    text = strip_think(_content_to_text(content))
    text = _strip_fence(text)
    if not text:
        return None, ""
    data = loads_first_json(text)
    if isinstance(data, dict):
        route = _normalize_route(data.get("next"))
        if route:
            reply = data.get("reply") or ""
            return route, str(reply).strip()
    m = _NEXT_FIELD_RE.search(text)
    if m:
        route = _normalize_route(m.group(1))
        if route:
            return route, ""
    return None, ""


def _keyword_route(text: str) -> str:
    """关键词兜底路由：命中异常关键词交给 anomaly_agent，否则 FINISH。"""
    if text and any(k in text for k in ANOMALY_KEYWORDS):
        return "anomaly_agent"
    return "FINISH"


def _make_supervisor(llm):
    def supervisor(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        # 已经路由过一次（或本轮已有子 Agent 回答）→ 直接结束，避免来回打转
        if state.get("routed") or _answered_this_turn(messages):
            return {"next": "FINISH", "reply": ""}

        prompt_messages = [SystemMessage(content=SUPERVISOR_PROMPT)] + messages
        route: str | None = None
        reply = ""

        # 通道 1：function calling
        try:
            result = llm.with_structured_output(
                Router, method="function_calling", include_raw=True
            ).invoke(prompt_messages)
            parsed = _as_dict(result.get("parsed"))
            if parsed:
                route = _normalize_route(parsed.get("next"))
                reply = str(parsed.get("reply") or "").strip()
            if route is None:
                raw = result.get("raw")
                fallback_route, fallback_reply = _parse_supervisor_output(
                    getattr(raw, "content", "")
                )
                route = route or fallback_route
                reply = reply or fallback_reply
        except Exception:
            route, reply = None, ""

        # 通道 2：模型输出 JSON 文本
        if route is None:
            try:
                raw = llm.invoke(prompt_messages)
                route, reply = _parse_supervisor_output(getattr(raw, "content", ""))
            except Exception:
                route, reply = None, ""

        # 通道 3：关键词兜底
        if route is None:
            route = _keyword_route(_last_user_text(messages))
            reply = ""

        if route == "FINISH" and not reply:
            reply = DEFAULT_FINISH_REPLY
        return {"next": route, "reply": reply, "routed": True}

    return supervisor


def _make_finalize():
    def finalize(state: AgentState) -> dict:
        messages = list(state.get("messages", []))
        if _answered_this_turn(messages):
            # 子 Agent 已给出回答，保留它的内容
            return {}
        reply = strip_think((state.get("reply") or "").strip()) or DEFAULT_FINISH_REPLY
        return {"messages": [AIMessage(content=reply)]}

    return finalize


def build_graph():
    llm = get_llm()
    builder = StateGraph(AgentState)
    builder.add_node("supervisor", _make_supervisor(llm))
    builder.add_node("anomaly_agent", build_anomaly_agent())
    builder.add_node("finalize", _make_finalize())
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next") or "FINISH",
        {"anomaly_agent": "anomaly_agent", "FINISH": "finalize"},
    )
    builder.add_edge("anomaly_agent", "supervisor")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=MemorySaver())


# 懒加载单例：仅在首次真正使用 AI 助手时才构建（避免无 MiniMax key 时拖垮整个应用启动）
_app_graph = None


def get_graph():
    global _app_graph
    if _app_graph is None:
        if not settings.minimax_enabled:
            raise RuntimeError("MiniMax 未配置（MINIMAX_API_KEY 为空），AI 助手暂不可用")
        _app_graph = build_graph()
    return _app_graph