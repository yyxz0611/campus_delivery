"""运营分析查询服务：SQL 先过只读闸门，再在只读会话中执行。"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, time as clock_time
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from ..database import engine
from . import ops_semantic
from .ops_sql_guard import SqlGuardError, validate_sql


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date, clock_time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def execute_sql(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_sql = validate_sql(sql)
    started = time.perf_counter()
    with engine.connect() as conn:
        query_only = conn.dialect.name == "sqlite"
        if query_only:
            conn.exec_driver_sql("PRAGMA query_only = ON")
        try:
            result = conn.execute(text(safe_sql), params or {})
            returns_rows = result.returns_rows
            columns = list(result.keys()) if returns_rows else []
            rows = (
                [{column: _jsonable(value) for column, value in zip(columns, record)} for record in result.fetchall()]
                if returns_rows
                else []
            )
            affected_rows = None if returns_rows else result.rowcount
        finally:
            if query_only:
                conn.exec_driver_sql("PRAGMA query_only = OFF")
            conn.rollback()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "sql": safe_sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "affected_rows": affected_rows,
        "limit_applied": safe_sql != sql.strip().rstrip(";").rstrip(),
        "elapsed_ms": elapsed_ms,
    }

class UnsupportedQuestion(Exception):
    """问题超出当前已支持的范围。"""


QUESTION_PATTERNS: tuple[dict[str, str], ...] = (
    {
        "label": "各楼栋超时统计",
        "pattern": r"(楼栋|宿舍).*(超时|迟到|未按时)",
        "sql": (
            "SELECT dorm_building, COUNT(*) AS overdue_total FROM orders "
            "WHERE expected_delivery_at IS NOT NULL "
            "AND expected_delivery_at < CURRENT_TIMESTAMP "
            "AND (delivered_at IS NULL OR delivered_at > expected_delivery_at) "
            "GROUP BY dorm_building ORDER BY overdue_total DESC"
        ),
    },
    {
        "label": "异常类型分布",
        "pattern": r"(异常|问题).*(类型|分布|原因)",
        "sql": (
            "SELECT anomaly_type, COUNT(*) AS total FROM anomalies "
            "GROUP BY anomaly_type ORDER BY total DESC"
        ),
    },
    {
        "label": "异常处理进度",
        "pattern": r"(异常|问题).*(状态|进度)",
        "sql": (
            "SELECT status, COUNT(*) AS total FROM anomalies "
            "GROUP BY status ORDER BY total DESC"
        ),
    },
    {
        "label": "各楼栋订单量",
        "pattern": r"(楼栋|宿舍).*(订单|数量|多少)",
        "sql": (
            "SELECT dorm_building, COUNT(*) AS total FROM orders "
            "GROUP BY dorm_building ORDER BY total DESC"
        ),
    },
    {
        "label": "订单状态分布",
        "pattern": r"(订单).*(状态|进度|多少)",
        "sql": (
            "SELECT status, COUNT(*) AS total FROM orders "
            "GROUP BY status ORDER BY total DESC"
        ),
    },
)

SUPPORTED_QUESTIONS: tuple[str, ...] = tuple(item["label"] for item in QUESTION_PATTERNS)

SUGGESTED_QUESTIONS: tuple[str, ...] = (
    "各楼栋超时订单数量",
    "异常类型分布",
    "异常处理进度",
    "各楼栋订单数量",
    "订单状态分布",
)

DANGEROUS_INTENT = re.compile(
    r"(删除|删掉|删了|清空|清除|移除|抹掉|drop|delete|truncate)",
    re.IGNORECASE,
)


def match_question(question: str) -> dict[str, str] | None:
    normalized = question.strip()
    if not normalized:
        return None
    for item in QUESTION_PATTERNS:
        if re.search(item["pattern"], normalized):
            return item
    return None


def ask(question: str) -> dict[str, Any]:
    if DANGEROUS_INTENT.search(question):
        raise SqlGuardError("问题包含删除类意图，自然语言入口只支持查询")

    matched = match_question(question)
    if matched is None:
        raise UnsupportedQuestion("暂不支持这个问题。当前可答：" + "、".join(SUPPORTED_QUESTIONS))

    payload = execute_sql(matched["sql"])
    payload["question"] = question
    payload["intent"] = matched["label"]
    payload["rows"] = ops_semantic.translate_rows(payload["columns"], payload["rows"])
    payload["column_labels"] = ops_semantic.result_column_labels(payload["columns"])
    payload["summary"] = ops_semantic.build_summary(payload["columns"], payload["rows"])
    payload["overview"] = ops_semantic.result_overview(payload["columns"], payload["rows"])
    return payload