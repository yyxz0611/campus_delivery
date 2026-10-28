from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import app
from app.routers.ops import OpsRawQuery, run_raw_sql


def test_route_is_mounted_under_api_ops() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/ops/raw" in paths


def test_openapi_exposes_request_body() -> None:
    operation = app.openapi()["paths"]["/api/ops/raw"]["post"]
    assert "requestBody" in operation
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("OpsRawQuery")


def test_select_is_allowed() -> None:
    result = run_raw_sql(OpsRawQuery(sql="SELECT COUNT(*) AS cnt FROM orders"))
    assert result["columns"] == ["cnt"]
    assert result["row_count"] == 1


def test_delete_is_rejected_with_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        run_raw_sql(OpsRawQuery(sql="DELETE FROM anomalies"))
    assert excinfo.value.status_code == 400
    assert "只读闸门" in excinfo.value.detail


def test_comment_is_rejected_with_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        run_raw_sql(OpsRawQuery(sql="SELECT * FROM orders -- drop"))
    assert excinfo.value.status_code == 400
    assert "注释" in excinfo.value.detail


def test_table_outside_whitelist_is_rejected_with_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        run_raw_sql(OpsRawQuery(sql="SELECT * FROM users"))
    assert excinfo.value.status_code == 400
    assert "白名单" in excinfo.value.detail


def test_missing_limit_is_added() -> None:
    result = run_raw_sql(OpsRawQuery(sql="SELECT id FROM orders"))
    assert result["limit_applied"] is True
    assert result["sql"].endswith("LIMIT 200")


def test_bad_column_still_returns_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        run_raw_sql(OpsRawQuery(sql="SELECT missing_column FROM orders"))
    assert excinfo.value.status_code == 400
    assert "SQL 执行失败" in excinfo.value.detail