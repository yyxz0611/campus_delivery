from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from app import models
from app.database import SessionLocal, engine
from app.services.ops_query_service import execute_sql
from app.services.ops_sql_guard import MAX_LIMIT, SqlGuardError

PREFIX = "OPS-T-"


@pytest.fixture()
def order_rows():
    db = SessionLocal()
    try:
        db.add_all(
            [
                models.Order(
                    order_no=f"{PREFIX}1",
                    customer_name="甲",
                    dorm_building="竹园",
                    dorm_room="101",
                    vendor_name="食堂",
                    status="delivered",
                    created_at=datetime(2026, 10, 1, 10, 0, 0),
                    expected_delivery_at=datetime(2026, 10, 1, 11, 0, 0),
                    delivered_at=datetime(2026, 10, 1, 10, 30, 0),
                ),
                models.Order(
                    order_no=f"{PREFIX}2",
                    customer_name="乙",
                    dorm_building="梅园",
                    dorm_room="201",
                    vendor_name="食堂",
                    status="abnormal",
                    created_at=datetime(2026, 10, 2, 11, 0, 0),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()
    yield
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM orders WHERE order_no LIKE '{PREFIX}%'"))


def test_select_returns_columns_and_rows(order_rows) -> None:
    result = execute_sql(
        f"SELECT order_no, dorm_building FROM orders WHERE order_no LIKE '{PREFIX}%' ORDER BY order_no"
    )
    assert result["columns"] == ["order_no", "dorm_building"]
    assert result["rows"] == [
        {"order_no": f"{PREFIX}1", "dorm_building": "竹园"},
        {"order_no": f"{PREFIX}2", "dorm_building": "梅园"},
    ]
    assert result["row_count"] == 2
    assert result["affected_rows"] is None


def test_datetime_value_is_json_safe(order_rows) -> None:
    result = execute_sql(f"SELECT created_at FROM orders WHERE order_no = '{PREFIX}1'")
    value = result["rows"][0]["created_at"]
    assert isinstance(value, str)
    assert value.startswith("2026-10-01")


def test_named_params_are_bound(order_rows) -> None:
    result = execute_sql("SELECT order_no FROM orders WHERE order_no = :no", {"no": f"{PREFIX}2"})
    assert result["rows"] == [{"order_no": f"{PREFIX}2"}]


def test_limit_is_appended(order_rows) -> None:
    result = execute_sql("SELECT order_no FROM orders")
    assert result["limit_applied"] is True
    assert result["sql"].endswith(f"LIMIT {MAX_LIMIT}")


def test_delete_is_rejected(order_rows) -> None:
    with pytest.raises(SqlGuardError, match="SELECT"):
        execute_sql("DELETE FROM orders")
    remaining = execute_sql(f"SELECT COUNT(*) AS cnt FROM orders WHERE order_no LIKE '{PREFIX}%'")
    assert remaining["rows"] == [{"cnt": 2}]


def test_ddl_is_rejected(order_rows) -> None:
    with pytest.raises(SqlGuardError):
        execute_sql("DROP TABLE orders")


def test_commented_payload_is_rejected(order_rows) -> None:
    with pytest.raises(SqlGuardError, match="注释"):
        execute_sql("SELECT * FROM orders -- then drop")


def test_sql_error_surfaces_after_guard(order_rows) -> None:
    with pytest.raises(Exception):
        execute_sql("SELECT missing_column FROM orders")


def test_query_only_blocks_write_even_if_guard_bypassed(order_rows) -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA query_only = ON")
        try:
            with pytest.raises(Exception):
                conn.execute(text("DELETE FROM orders"))
        finally:
            conn.exec_driver_sql("PRAGMA query_only = OFF")
            conn.rollback()
    remaining = execute_sql(f"SELECT COUNT(*) AS cnt FROM orders WHERE order_no LIKE '{PREFIX}%'")
    assert remaining["rows"] == [{"cnt": 2}]