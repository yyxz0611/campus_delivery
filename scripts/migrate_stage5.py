"""阶段5 迁移：anomalies 加 reported_by_user_id + reported_role。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/migrate_stage5.py
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
    if "anomalies" not in set(insp.get_table_names()):
        print("anomalies 表不存在，跳过")
        return
    cols = {c["name"] for c in insp.get_columns("anomalies")}
    with engine.begin() as conn:
        if "reported_by_user_id" not in cols:
            conn.execute(text("ALTER TABLE anomalies ADD COLUMN reported_by_user_id INT NULL"))
            print("anomalies.reported_by_user_id 已添加")
        if "reported_role" not in cols:
            conn.execute(text("ALTER TABLE anomalies ADD COLUMN reported_role VARCHAR(16) NOT NULL DEFAULT ''"))
            print("anomalies.reported_role 已添加")
    print("阶段5迁移完成")


if __name__ == "__main__":
    main()