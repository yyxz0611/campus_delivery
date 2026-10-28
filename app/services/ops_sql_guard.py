"""SQL 只读闸门：注释、多语句、语句类型、关键字、表白名单、LIMIT 六道检查。"""
from __future__ import annotations

import re

ALLOWED_TABLES: frozenset[str] = frozenset({"orders", "anomalies"})
MAX_LIMIT = 200
MAX_SQL_LENGTH = 2000

_COMMENT_MARKERS: tuple[tuple[str, str], ...] = (
    ("--", "单行注释"),
    ("/*", "块注释"),
    ("*/", "块注释结束符"),
    ("#", "井号注释"),
)

_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\binsert\b", "INSERT"),
    (r"\bupdate\b", "UPDATE"),
    (r"\bdelete\b", "DELETE"),
    (r"\bdrop\b", "DROP"),
    (r"\balter\b", "ALTER"),
    (r"\bcreate\b", "CREATE"),
    (r"\btruncate\b", "TRUNCATE"),
    (r"\bgrant\b", "GRANT"),
    (r"\brevoke\b", "REVOKE"),
    (r"\battach\b", "ATTACH"),
    (r"\bdetach\b", "DETACH"),
    (r"\bpragma\b", "PRAGMA"),
    (r"\bvacuum\b", "VACUUM"),
    (r"\breindex\b", "REINDEX"),
    (r"\binto\b", "INTO"),
    (r"\bload_extension\b", "LOAD_EXTENSION"),
)

_TABLE_REF_RE = re.compile(r"(?i)\b(?:from|join)\s+([a-z_][\w]*)")
_IMPLICIT_JOIN_RE = re.compile(r"(?i)\bfrom\s+[a-z_][\w]*\s+(?:as\s+)?[a-z_][\w]*\s*,")
_LIMIT_RE = re.compile(r"(?i)\blimit\s+(\d+)")


class SqlGuardError(ValueError):
    """SQL 未通过只读闸门。"""


def _strip_literals(sql: str) -> str:
    out: list[str] = []
    quote = ""
    for char in sql:
        if quote:
            out.append(" ")
            if char == quote:
                quote = ""
            continue
        if char in ("'", '"'):
            quote = char
            out.append(" ")
            continue
        out.append(char)
    return "".join(out)


def _reject_comments(sql: str) -> None:
    for marker, label in _COMMENT_MARKERS:
        if marker in sql:
            raise SqlGuardError(f"禁止包含{label}，注释可用来切断关键字")


def _reject_multi_statement(sql: str) -> str:
    body = sql.rstrip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    if ";" in body:
        raise SqlGuardError("禁止一次提交多条语句")
    return body


def validate_sql(sql: str) -> str:
    if not isinstance(sql, str):
        raise SqlGuardError("SQL 必须是字符串")
    raw = sql.strip()
    if not raw:
        raise SqlGuardError("SQL 不能为空")
    if len(raw) > MAX_SQL_LENGTH:
        raise SqlGuardError(f"SQL 长度不得超过 {MAX_SQL_LENGTH} 字符")

    _reject_comments(raw)
    body = _reject_multi_statement(raw)

    if not re.match(r"(?i)^select\b", body):
        raise SqlGuardError("只允许 SELECT 查询")

    literal_free = _strip_literals(body)

    for pattern, label in _FORBIDDEN_PATTERNS:
        if re.search(pattern, literal_free, re.IGNORECASE):
            raise SqlGuardError(f"禁止使用关键字 {label}")

    tables = {name.lower() for name in _TABLE_REF_RE.findall(literal_free)}
    if not tables:
        raise SqlGuardError("未识别到查询的表，请显式写 FROM <表名>")
    disallowed = sorted(tables - ALLOWED_TABLES)
    if disallowed:
        raise SqlGuardError(
            f"表 {', '.join(disallowed)} 不在白名单内，仅允许 {', '.join(sorted(ALLOWED_TABLES))}"
        )

    if _IMPLICIT_JOIN_RE.search(literal_free):
        raise SqlGuardError("禁止用逗号连接多张表，请改用 JOIN")

    limit = _LIMIT_RE.search(literal_free)
    if limit:
        if int(limit.group(1)) > MAX_LIMIT:
            raise SqlGuardError(f"LIMIT 不得超过 {MAX_LIMIT}")
        return body
    return f"{body} LIMIT {MAX_LIMIT}"