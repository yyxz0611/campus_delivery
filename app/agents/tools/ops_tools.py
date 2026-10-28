# -*- coding: utf-8 -*-
"""运营分析工具：把自然语言业务问题交给确定性查询服务，回传结构化表格数据。

工具只做「调服务 + 序列化」，不生成 SQL，避免模型自由发挥写出错语句。
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from ...services import ops_query_service
from ..context import get_current_user

logger = logging.getLogger(__name__)

ADMIN_ONLY_REPLY = "运营统计仅管理员可用。如需查看经营数据，请联系管理员。"


@tool
def ask_ops_metrics(question: str) -> str:
    """查询校园外卖平台的运营指标。

    适用于：各楼栋超时订单数量、各楼栋订单数量、异常类型分布、异常处理进度、订单状态分布。
    返回 JSON 字符串，含 summary（一句话结论）、columns、column_labels、rows、overview。
    仅管理员可用；非管理员会返回 error 字段。
    """
    current = get_current_user()
    if not current or current[1] != "admin":
        return json.dumps({"error": ADMIN_ONLY_REPLY}, ensure_ascii=False)

    try:
        result = ops_query_service.ask(question)
    except ops_query_service.UnsupportedQuestion as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 工具层不抛异常，统一转成 error 文本
        logger.exception("运营查询失败: %s", exc)
        return json.dumps({"error": f"查询未成功：{exc}"}, ensure_ascii=False)

    return json.dumps(
        {
            "summary": result.get("summary", ""),
            "intent": result.get("intent", ""),
            "columns": result.get("columns", []),
            "column_labels": result.get("column_labels", []),
            "rows": result.get("rows", []),
            "overview": result.get("overview", {}),
        },
        ensure_ascii=False,
    )


OPS_TOOLS = [ask_ops_metrics]