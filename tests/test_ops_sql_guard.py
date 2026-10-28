from __future__ import annotations

import pytest

from app.services.ops_sql_guard import MAX_LIMIT, SqlGuardError, validate_sql


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM anomalies",
        "UPDATE orders SET status = 'delivered'",
        "INSERT INTO orders (id) VALUES (99)",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN x TEXT",
        "CREATE TABLE evil (id INTEGER)",
        "TRUNCATE TABLE orders",
        "PRAGMA query_only = OFF",
        "ATTACH DATABASE 'x.db' AS x",
        "VACUUM",
    ],
)
def test_non_select_is_rejected(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders -- 注释",
        "SELECT * FROM orders /* 块注释 */",
        "SELECT * FROM orders # 井号",
        "SEL/**/ECT * FROM orders",
        "SELECT * FROM orders /*",
    ],
)
def test_comments_are_rejected(sql: str) -> None:
    with pytest.raises(SqlGuardError, match="注释"):
        validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders; DROP TABLE orders",
        "SELECT * FROM orders; SELECT * FROM anomalies",
    ],
)
def test_multiple_statements_are_rejected(sql: str) -> None:
    with pytest.raises(SqlGuardError, match="多条语句"):
        validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM orders o, users u",
        "SELECT * FROM orders o, users u WHERE o.id = u.id",
        "SELECT * FROM orders UNION SELECT * FROM users",
        "SELECT * FROM orders JOIN users ON 1 = 1",
    ],
)
def test_table_whitelist_is_enforced(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, dorm_building FROM orders",
        "SELECT dorm_building, COUNT(*) AS cnt FROM orders GROUP BY dorm_building",
        "SELECT a.anomaly_type, o.dorm_building FROM anomalies a JOIN orders o ON o.id = a.order_id",
        "SELECT * FROM orders WHERE status = 'delivered' LIMIT 10",
    ],
)
def test_allowed_queries_pass(sql: str) -> None:
    assert validate_sql(sql)


def test_limit_is_appended_when_missing() -> None:
    assert validate_sql("SELECT * FROM orders").endswith(f"LIMIT {MAX_LIMIT}")


def test_existing_limit_is_kept() -> None:
    sql = "SELECT * FROM orders LIMIT 10"
    assert validate_sql(sql) == sql


def test_oversized_limit_is_rejected() -> None:
    with pytest.raises(SqlGuardError, match="LIMIT"):
        validate_sql("SELECT * FROM orders LIMIT 5000")


def test_keywords_inside_string_literal_are_not_misjudged() -> None:
    sql = "SELECT * FROM orders WHERE food_items = 'delete from users'"
    assert validate_sql(sql)


def test_select_into_is_rejected() -> None:
    with pytest.raises(SqlGuardError, match="INTO"):
        validate_sql("SELECT * FROM orders INTO OUTFILE '/tmp/x'")


@pytest.mark.parametrize(
    "sql",
    [
        "select * from orders into outfile '/tmp/x'",
        "SELECT * FROM orders Into OUTFILE '/tmp/x'",
        "SELECT * FROM orders WHERE status = 'delivered' UNION ALL SELECT * FROM users",
    ],
)
def test_keyword_matching_is_case_insensitive(sql: str) -> None:
    with pytest.raises(SqlGuardError):
        validate_sql(sql)


def test_table_name_is_case_insensitive() -> None:
    assert validate_sql("SELECT * FROM ORDERS")


def test_statement_without_table_is_rejected() -> None:
    with pytest.raises(SqlGuardError, match="FROM"):
        validate_sql("SELECT 1")


def test_empty_and_oversized_sql_are_rejected() -> None:
    with pytest.raises(SqlGuardError):
        validate_sql("   ")
    with pytest.raises(SqlGuardError):
        validate_sql("SELECT * FROM orders WHERE order_no = '" + "x" * 2000 + "'")


def test_trailing_semicolon_is_tolerated() -> None:
    assert validate_sql("SELECT * FROM orders;").endswith(f"LIMIT {MAX_LIMIT}")