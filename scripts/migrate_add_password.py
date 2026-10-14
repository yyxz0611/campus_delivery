"""给 users 表补 password_hash 列（生产 RDS 已建表，create_all 不会自动加列）。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/migrate_add_password.py
可重复运行：列已存在则跳过。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

CHECK = (
    "SELECT COUNT(*) FROM information_schema.columns "
    "WHERE table_schema = DATABASE() AND table_name = 'users' AND column_name = 'password_hash'"
)
ALTER = "ALTER TABLE users ADD COLUMN password_hash VARCHAR(128) NOT NULL DEFAULT ''"


def main() -> None:
    with engine.begin() as conn:
        exists = conn.execute(text(CHECK)).scalar()
        if exists:
            print("password_hash 列已存在，跳过")
            return
        conn.execute(text(ALTER))
        print("已添加 users.password_hash 列（VARCHAR(128) NOT NULL DEFAULT ''）")


if __name__ == "__main__":
    main()