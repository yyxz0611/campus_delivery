"""只读数据库 MCP server。

通过 stdio 上的 JSON-RPC 2.0 向 AI 暴露项目数据库的表结构、样本数据与只读查询能力，
使 AI 无需反复读取 models.py 即可获得真实上下文。零第三方依赖。

安全边界：只允许 SELECT；禁止 DDL/DML 与注释；表白名单；强制行数上限；手机号脱敏。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "campus-db"
SERVER_VERSION = "1.0.0"

MAX_ROWS = 200
DEFAULT_SAMPLE = 5

DB_PATH = Path(__file__).resolve().parents[2] / "campus_delivery.db"

ALLOWED_TABLES = {
    "users",
    "user_credentials",
    "orders",
    "delivery_nodes",
    "photo_records",
    "anomalies",
    "vehicle_trips",
    "staff_shifts",
    "notification_subscriptions",
    "notifications",
    "notification_user_states",
    "balance_transactions",
}

FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|replace|truncate|grant|revoke)\b",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"\b(1[3-9]\d)(\d{4})(\d{4})\b")
EMAIL_PATTERN = re.compile(r"\b([\w.%+-]{1,3})[\w.%+-]*(@[\w.-]+\.[A-Za-z]{2,})\b")
SECRET_PATTERN = re.compile(r"\b(AK|SK|SECRET|PASSWORD|TOKEN)\b", re.IGNORECASE)


def _log(message: str) -> None:
    sys.stderr.write(f"[campus-db] {message}\n")
    sys.stderr.flush()


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在：{DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _mask(value):
    if isinstance(value, str):
        value = PHONE_PATTERN.sub(r"\1****\3", value)
        value = EMAIL_PATTERN.sub(r"\1***\2", value)
    return value


def _mask_row(row: dict) -> dict:
    masked = {}
    for key, value in row.items():
        if SECRET_PATTERN.search(key):
            masked[key] = "[已脱敏]"
        else:
            masked[key] = _mask(value)
    return masked


def list_tables() -> dict:
    conn = _connect()
    try:
        tables = []
        for name in sorted(ALLOWED_TABLES):
            try:
                count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error:
                continue
            tables.append({"table": name, "rows": count})
        return {"database": DB_PATH.name, "table_count": len(tables), "tables": tables}
    finally:
        conn.close()


def describe_table(name: str) -> dict:
    if name not in ALLOWED_TABLES:
        raise ValueError(f"表不在白名单：{name}")
    conn = _connect()
    try:
        columns = []
        for row in conn.execute(f'PRAGMA table_info("{name}")'):
            columns.append(
                {
                    "name": row["name"],
                    "type": row["type"],
                    "not_null": bool(row["notnull"]),
                    "primary_key": bool(row["pk"]),
                }
            )
        return {"table": name, "column_count": len(columns), "columns": columns}
    finally:
        conn.close()


def sample_rows(table: str, limit: int = DEFAULT_SAMPLE) -> dict:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"表不在白名单：{table}")
    limit = max(1, min(int(limit), 50))
    conn = _connect()
    try:
        rows = conn.execute(f'SELECT * FROM "{table}" LIMIT {limit}').fetchall()
        return {
            "table": table,
            "returned": len(rows),
            "rows": [_mask_row(dict(row)) for row in rows],
        }
    finally:
        conn.close()


def run_readonly_query(sql: str) -> dict:
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise ValueError("SQL 为空")
    if not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
        raise ValueError("只允许 SELECT / WITH 查询")
    if FORBIDDEN_SQL.search(statement):
        raise ValueError("SQL 含禁用关键字")
    if "--" in statement or "/*" in statement:
        raise ValueError("SQL 不允许注释")

    mentioned = set(re.findall(r'\b(?:from|join)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', statement, re.IGNORECASE))
    illegal = {name for name in mentioned if name.lower() not in ALLOWED_TABLES}
    if illegal:
        raise ValueError(f"访问了白名单外的表：{sorted(illegal)}")

    has_limit = re.search(r"\blimit\b", statement, re.IGNORECASE) is not None
    final_sql = statement if has_limit else f"{statement} LIMIT {MAX_ROWS}"

    conn = _connect()
    try:
        cursor = conn.execute(final_sql)
        rows = cursor.fetchmany(MAX_ROWS)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return {
            "sql": final_sql,
            "row_count": len(rows),
            "columns": columns,
            "rows": [_mask_row(dict(row)) for row in rows],
        }
    finally:
        conn.close()


TOOLS = [
    {
        "name": "list_tables",
        "description": "列出数据库白名单内的所有表及各自行数，用于快速建立数据全景。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "describe_table",
        "description": "查看单张表的字段名、类型、非空与主键信息。写 SQL 或改模型前应先调用。",
        "inputSchema": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "表名"}},
            "required": ["table"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sample_rows",
        "description": "抽取指定表的若干行样本数据，手机号自动脱敏。用于理解字段语义与真实取值。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "表名"},
                "limit": {"type": "integer", "description": "行数，1-50，默认 5"},
            },
            "required": ["table"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_readonly_query",
        "description": "执行只读 SELECT 查询。禁止 DDL/DML、注释与白名单外表，未写 LIMIT 时自动追加 200 行上限。",
        "inputSchema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "SELECT 或 WITH 语句"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]


def _dispatch_tool(name: str, arguments: dict) -> dict:
    if name == "list_tables":
        return list_tables()
    if name == "describe_table":
        return describe_table(arguments["table"])
    if name == "sample_rows":
        return sample_rows(arguments["table"], arguments.get("limit", DEFAULT_SAMPLE))
    if name == "run_readonly_query":
        return run_readonly_query(arguments["sql"])
    raise ValueError(f"未知工具：{name}")


def _handle(request: dict) -> dict | None:
    method = request.get("method")
    request_id = request.get("id")

    if request_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = _dispatch_tool(name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                    "isError": True,
                },
            }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    _log(f"started, db={DB_PATH}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _log(f"invalid json: {exc}")
            continue

        response = _handle(request)
        if response is None:
            continue

        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()