import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent  # campus_delivery 目录
sys.path.insert(0, str(ROOT))

DB_FILE = ROOT / "test_tmp.db"
if DB_FILE.exists():
    DB_FILE.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_FILE}"
os.environ["REDIS_URL"] = ""  # 强制降级进程内
os.environ["HW_OCR_ENABLED"] = ""  # 测试环境关闭 OCR，走本地质量审核

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    return TestClient(app)