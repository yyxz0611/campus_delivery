# -*- coding: utf-8 -*-
"""运营分析子 Agent：把业务统计问题交给运营工具，并回传结构化表格供前端渲染。

两条路径：
1. 正常路径：ReAct 循环调 ask_ops_metrics，从 ToolMessage 里取出结构化结果；
2. 降级路径：模型不可用或没调工具时，直接走确定性查询服务，保证一定有结果。
"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from ...services import ops_query_service
from ..context import get_current_user
from ..llm import get_llm
from ..prompts import OPS_AGENT_PROMPT
from ..tools.ops_tools import ADMIN_ONLY_REPLY, OPS_TOOLS

logger = logging.getLogger(__name__)

AGENT_ERROR_REPLY = "抱歉，运营数据暂时取不到，请稍后重试，或直接联系管理员。"


def _last_user_text(messages: list) -> str:
    for message in reversed(messages or []):
        if getattr(message, "type", None) in ("user", "human"):
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
    return ""


def _extract_table(messages: list) -> dict | None:
    for message in reversed(messages or []):
        if not isinstance(message, ToolMessage):
            continue
        if not isinstance(message.content, str):
            continue
        try:
            data = json.loads(message.content)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("rows"):
            return {
                "summary": data.get("summary", ""),
                "intent": data.get("intent", ""),
                "columns": data.get("columns", []),
                "column_labels": data.get("column_labels", []),
                "rows": data.get("rows", []),
                "overview": data.get("overview", {}),
            }
    return None


def _direct_answer(text: str) -> dict:
    current = get_current_user()
    if not current or current[1] != "admin":
        return {"messages": [AIMessage(content=ADMIN_ONLY_REPLY)]}

    try:
        result = ops_query_service.ask(text)
    except ops_query_service.UnsupportedQuestion as exc:
        return {"messages": [AIMessage(content=f"这个问题目前还答不了。{exc}")]}
    except Exception as exc:  # noqa: BLE001
        logger.exception("运营降级查询失败: %s", exc)
        return {"messages": [AIMessage(content=AGENT_ERROR_REPLY)]}

    reply = result.get("summary") or "已取到最新数据，明细见下方表格。"
    return {
        "messages": [AIMessage(content=reply)],
        "table": {
            "summary": result.get("summary", ""),
            "intent": result.get("intent", ""),
            "columns": result.get("columns", []),
            "column_labels": result.get("column_labels", []),
            "rows": result.get("rows", []),
            "overview": result.get("overview", {}),
        },
    }


def build_ops_agent():
    inner = create_react_agent(get_llm(), OPS_TOOLS, prompt=OPS_AGENT_PROMPT)

    def safe_ops_agent(state):
        messages = list(state.get("messages", []))
        try:
            result = inner.invoke(state)
            produced = list(result.get("messages", [])) if isinstance(result, dict) else list(result or [])
            table = _extract_table(produced)
            if table is not None:
                return {"messages": produced, "table": table}
        except Exception as exc:  # noqa: BLE001
            logger.exception("运营 Agent 执行失败: %s", exc)
        return _direct_answer(_last_user_text(messages))

    return safe_ops_agent