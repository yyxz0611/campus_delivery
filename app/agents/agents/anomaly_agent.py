# -*- coding: utf-8 -*-
"""异常应急子 Agent：ReAct 循环（思考 -> 调工具 -> 回答）。"""
from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent

from ..llm import get_llm
from ..prompts import ANOMALY_AGENT_PROMPT
from ..tools.anomaly_tools import ANOMALY_TOOLS
from ..tools.notification_tools import NOTIFICATION_TOOLS

logger = logging.getLogger(__name__)

AGENT_ERROR_REPLY = "抱歉，我这边暂时连接不上模型服务，没能完成这次查询。请稍后重试，或直接联系人工客服处理。"

# 异常应急 Agent 的全部工具：订单轨迹 / 异常上报 / 向通知中心发消息
AGENT_TOOLS = list(ANOMALY_TOOLS) + list(NOTIFICATION_TOOLS)


def build_anomaly_agent():
    """构建异常应急 ReAct agent，绑定 2.0 服务层包装出的工具。

    外层包一层兜底：模型/工具异常不能让整轮对话失败，降级为一条说明性回复。
    """
    inner = create_react_agent(get_llm(), AGENT_TOOLS, prompt=ANOMALY_AGENT_PROMPT)

    def safe_anomaly_agent(state):
        try:
            return inner.invoke(state)
        except Exception as e:  # noqa: BLE001
            logger.exception("异常应急 Agent 执行失败: %s", e)
            return {"messages": [AIMessage(content=f"{AGENT_ERROR_REPLY}（{e}）")]}

    return safe_anomaly_agent