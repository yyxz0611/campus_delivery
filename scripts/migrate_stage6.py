"""阶段6 迁移：创建 balance_transactions 表 + users 加 balance 列。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/migrate_stage6.py
可重复运行：已存在则跳过。
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


def main() -> None:
    insp = inspect(engine)

    cols = {c["name"] for c in insp.get_columns("users")}
    with engine.begin() as conn:
        if "balance" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN balance FLOAT NOT NULL DEFAULT 0.0"))
            print("users.balance 已添加")
        else:
            print("users.balance 已存在，跳过")

    table_name = "balance_transactions"
    if table_name not in set(insp.get_table_names()):
        Base.metadata.tables[table_name].create(engine, checkfirst=True)
        print("balance_transactions 表已创建")
    else:
        print("balance_transactions 表已存在，跳过")

    print("阶段6迁移完成")


if __name__ == "__main__":
    main()