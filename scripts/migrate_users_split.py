"""将旧 users 表（单角色+密码）拆分为 users（自然人）+ user_credentials（多角色凭据）。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/migrate_users_split.py
可重复运行：已完成则跳过。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from sqlalchemy import inspect, text  # noqa: E402

from app import models  # noqa: E402, F401
from app.database import Base, SessionLocal, engine  # noqa: E402


def main() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "user_credentials" in tables:
        print("已是新结构（user_credentials 已存在），跳过")
        return

    users_cols = {c["name"] for c in insp.get_columns("users")} if "users" in tables else set()
    if "email" in users_cols:
        Base.metadata.create_all(bind=engine)
        print("users 已是新结构，已补建 user_credentials")
        return

    if "password_hash" not in users_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(128) NOT NULL DEFAULT ''"))

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users RENAME TO users_old"))
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT name, phone, role, password_hash FROM users_old")).fetchall()
        user_ids: dict[str, models.User] = {}
        for name, phone, role, password_hash in rows:
            user = user_ids.get(phone)
            if user is None:
                user = models.User(name=name or "用户", phone=phone)
                db.add(user)
                db.flush()
                user_ids[phone] = user
            db.add(models.UserCredential(user_id=user.id, role=role or "rider", password_hash=password_hash or ""))
        db.commit()
        print(f"迁移完成：{len(user_ids)} 个用户")
    finally:
        db.close()
    print("旧表 users_old 已保留（可手动删除）")


if __name__ == "__main__":
    main()