"""迁移脚本：创建 notifications + notification_user_states 表。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, engine, init_db
from app import models  # noqa: F401


def main():
    init_db()
    print("notifications + notification_user_states 表已就绪")


if __name__ == "__main__":
    main()