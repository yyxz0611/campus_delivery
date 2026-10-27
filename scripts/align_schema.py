"""通用 Schema 对齐：按 models.py 自动补齐数据库中缺失的列（幂等，可重复运行）。

背景
----
Base.metadata.create_all() 只负责建新表，不会给已存在的旧表补列。
models.Order 新增 source / rider_user_id 后，旧库的 orders 表缺这两列，
POST /api/orders 会直接 500：
    table orders has no column named source

本脚本遍历所有模型表，比对实际库结构，把缺失的列补上（缺失的表则直接建表）。
新增非空列时会带上标量默认值，无法给出安全默认值的列一律按可空处理。

用法（在 campus_delivery 目录下执行）
------------------------------------
    /root/venv/bin/python scripts/align_schema.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from sqlalchemy import inspect, text  # noqa: E402

from app.database import engine, Base  # noqa: E402
from app import models  # noqa: E402


def _default_literal(col) -> str | None:
    """把 Python 侧标量默认值转成 SQL 字面量；非标量（如 now 函数）返回 None。"""
    default = col.default
    if default is None or not default.is_scalar:
        return None
    val = default.arg
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return "'" + val.replace("'", "''") + "'"
    return None


def main() -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    changed = 0

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            print(f"[建表] {table_name}")
            table.create(engine, checkfirst=True)
            changed += 1
            continue

        existing_cols = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name in existing_cols:
                continue
            ddl = col.type.compile(engine.dialect)
            nullable = "NULL" if col.nullable else "NOT NULL"
            default = _default_literal(col)
            if not col.nullable and default is None:
                nullable = "NULL"
                default = None
            piece = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {ddl} {nullable}"
            if default is not None:
                piece += f" DEFAULT {default}"
            print(f"[补列] {piece}")
            with engine.begin() as conn:
                conn.execute(text(piece))
            changed += 1

    print(f"Schema 对齐完成，共 {changed} 处变更")


if __name__ == "__main__":
    main()