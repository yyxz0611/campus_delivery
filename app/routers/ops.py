"""运营分析路由：SQL 经只读闸门后执行，仅管理员可访问。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth_deps import require_role
from ..services import ops_query_service
from ..services.ops_sql_guard import SqlGuardError

router = APIRouter(prefix="/api/ops", tags=["ops"])

ADMIN_ONLY = [Depends(require_role("admin"))]


class OpsAskQuery(BaseModel):
    question: str


class OpsRawQuery(BaseModel):
    sql: str


@router.post("/ask", dependencies=ADMIN_ONLY)
def ask_question(payload: OpsAskQuery):
    try:
        return ops_query_service.ask(payload.question)
    except ops_query_service.UnsupportedQuestion as exc:
        raise HTTPException(
            400,
            {
                "message": str(exc),
                "suggestions": list(ops_query_service.SUGGESTED_QUESTIONS),
            },
        ) from exc
    except SqlGuardError as exc:
        raise HTTPException(400, f"SQL 被只读闸门拒绝: {exc}") from exc
    except Exception as exc:
        raise HTTPException(400, f"查询失败: {exc}") from exc


@router.post("/raw", dependencies=ADMIN_ONLY)
def run_raw_sql(payload: OpsRawQuery):
    try:
        return ops_query_service.execute_sql(payload.sql)
    except SqlGuardError as exc:
        raise HTTPException(400, f"SQL 被只读闸门拒绝: {exc}") from exc
    except Exception as exc:
        raise HTTPException(400, f"SQL 执行失败: {exc}") from exc