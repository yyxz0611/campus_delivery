from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.models import Anomaly, Order
from app.services import ops_semantic as semantic

REAL_DB = Path(__file__).resolve().parent.parent / "campus_delivery.db"


def _real_db_values(column: str, table: str) -> list[str]:
    if not REAL_DB.exists():
        pytest.skip("真实库文件不存在，跳过与库对账")
    with sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True) as conn:
        rows = conn.execute(f"SELECT DISTINCT {column} FROM {table}").fetchall()
    return sorted(str(row[0]) for row in rows)


def test_covers_only_requested_tables() -> None:
    assert set(semantic.COVERED_TABLES) == {"orders", "anomalies"}


def test_field_names_match_orm_columns() -> None:
    expected = {
        "orders": {column.name for column in Order.__table__.columns},
        "anomalies": {column.name for column in Anomaly.__table__.columns},
    }
    for table, columns in expected.items():
        declared = {field["name"] for field in semantic.get_table_semantic(table)["fields"]}
        assert declared == columns, table


def test_order_status_covers_all_real_values() -> None:
    declared = semantic.order_status_values()
    real = _real_db_values("status", "orders")
    assert len(declared) == 8
    assert set(declared) == set(real)


def test_order_status_has_business_attributes() -> None:
    values = semantic.get_enum_semantic("order_status")["values"]
    assert len(values) == 8
    for value, item in values.items():
        assert item["label"]
        assert value in {"abnormal"} or item["stage"] is not None
    assert values["delivered"]["is_completed"] is True
    assert values["abnormal"]["off_flow"] is True
    assert sum(1 for item in values.values() if item["is_completed"]) == 1


def test_cancelled_is_reserved_not_selectable() -> None:
    assert "cancelled" not in semantic.order_status_values()
    assert "cancelled" not in _real_db_values("status", "orders")
    assert "cancelled" in semantic.get_enum_semantic("order_status")["reserved"]


def test_anomaly_enums_cover_real_values() -> None:
    assert set(semantic.get_enum_semantic("anomaly_type")["values"]) >= set(
        _real_db_values("anomaly_type", "anomalies")
    )
    assert set(semantic.get_enum_semantic("anomaly_status")["values"]) >= set(
        _real_db_values("status", "anomalies")
    )
    roles = semantic.get_enum_semantic("reported_role")
    assert set(roles["values"]) >= {value for value in _real_db_values("reported_role", "anomalies") if value}
    assert "" in _real_db_values("reported_role", "anomalies")
    assert "" in roles["missing_value"]


def test_sensitive_fields_are_declared_and_marked() -> None:
    declared = {
        f"{table}.{field['name']}"
        for table, meta in semantic.SEMANTIC_TABLES.items()
        for field in meta["fields"]
    }
    assert semantic.SENSITIVE_FIELDS <= declared
    for qualified in semantic.SENSITIVE_FIELDS:
        table, name = qualified.split(".", 1)
        field = next(f for f in semantic.SEMANTIC_TABLES[table]["fields"] if f["name"] == name)
        assert field["role"] == "sensitive"


def test_metrics_use_sets_not_single_status() -> None:
    transit = semantic.SEMANTIC_METRICS["in_transit_count"]["where"]
    assert "NOT IN" in transit
    timeout = semantic.SEMANTIC_METRICS["timeout_delivered_count"]["where"]
    assert "delivered_at > orders.expected_delivery_at" in timeout
    overdue = semantic.SEMANTIC_METRICS["overdue_undelivered_count"]["where"]
    assert ":now" in overdue


def test_render_prompt_contains_all_statuses_and_guardrails() -> None:
    prompt = semantic.render_schema_prompt()
    for value in semantic.order_status_values():
        assert value in prompt
    assert "cancelled 不可用" in prompt
    assert "不得出现在 SELECT 结果中" in prompt
    assert "anomalies.order_id = orders.id" in prompt


def test_render_prompt_rejects_unknown_table() -> None:
    with pytest.raises(KeyError):
        semantic.render_schema_prompt(["users"])