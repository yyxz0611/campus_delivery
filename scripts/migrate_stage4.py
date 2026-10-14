"""阶段4 迁移：users 加 dorm_building/dorm_room，orders 加 rider_user_id。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/migrate_stage4.py
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

from app.database import engine  # noqa: E402


def main() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "dorm_building" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN dorm_building VARCHAR(64) NOT NULL DEFAULT ''"))
                print("users.dorm_building 已添加")
            if "dorm_room" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN dorm_room VARCHAR(32) NOT NULL DEFAULT ''"))
                print("users.dorm_room 已添加")

    if "orders" in tables:
        cols = {c["name"] for c in insp.get_columns("orders")}
        with engine.begin() as conn:
            if "rider_user_id" not in cols:
                conn.execute(text("ALTER TABLE orders ADD COLUMN rider_user_id INT NULL"))
                print("orders.rider_user_id 已添加")

    print("阶段4迁移完成")


if __name__ == "__main__":
    main()