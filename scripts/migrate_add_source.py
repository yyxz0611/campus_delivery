"""给 orders 表补 source 列（生产 RDS 已建表，create_all 不会自动加列）。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/migrate_add_source.py
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
    "WHERE table_schema = DATABASE() AND table_name = 'orders' AND column_name = 'source'"
)
ALTER = "ALTER TABLE orders ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'ocr'"


def main() -> None:
    with engine.begin() as conn:
        exists = conn.execute(text(CHECK)).scalar()
        if exists:
            print("source 列已存在，跳过")
            return
        conn.execute(text(ALTER))
        print("已添加 orders.source 列（VARCHAR(16) NOT NULL DEFAULT 'ocr'）")


if __name__ == "__main__":
    main()