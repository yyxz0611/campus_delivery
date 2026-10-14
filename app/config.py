"""应用配置：支持本地开发（SQLite + 进程内缓存）与华为云生产（RDS / DCS Redis）一键切换。

所有可配置项都通过环境变量注入，优先读取项目根目录下的 .env 文件。
生产环境只需设置 DATABASE_URL 与 REDIS_URL 即可对接华为云 RDS 与 DCS Redis。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env（若存在）
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


class Settings:
    """全局配置对象。"""

    app_name: str = "校园外卖配送对接平台"
    version: str = "1.0.0"

    # ---- 数据库：默认本地 SQLite，生产切换华为云 RDS ----
    # MySQL:   mysql+pymysql://<user>:<pass>@<host>:<port>/<db>
    # PG:      postgresql+psycopg2://<user>:<pass>@<host>:<port>/<db>
    database_url: str = _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'campus_delivery.db'}")

    # ---- Redis：未配置或连接失败时自动降级为进程内缓存/队列（不影响主流程）----
    redis_url: str = _env("REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_enabled_default: bool = bool(_env("REDIS_URL", ""))

    # ---- 文件/照片存储 ----
    upload_dir: Path = BASE_DIR / "static" / "uploads"
    static_dir: Path = BASE_DIR / "static"
    frontend_dir: Path = BASE_DIR / "frontend"

    # ---- 作业规则 ----
    anomaly_timeout_seconds: int = int(_env("ANOMALY_TIMEOUT_SECONDS", "600"))  # 10 分钟无进度触发补偿
    compensation_amount: float = float(_env("COMPENSATION_AMOUNT", "5.0"))  # 默认补偿金额

    # ---- 华为云 OCR（生产环境用于校验照片中单号/寝室号，未配置则本地质量审核）----
    huawei_ocr_enabled: bool = bool(_env("HW_OCR_ENABLED", ""))

    # ---- 华为云 AK/SK 与 Region（用于调用 OCR、开通 RDS/Redis 等云 API）----
    huawei_ak: str = _env("HW_AK", "")
    huawei_sk: str = _env("HW_SK", "")
    huawei_region: str = _env("HW_REGION", "cn-north-4")
    huawei_credentials_ready: bool = bool(huawei_ak and huawei_sk)

    # ---- 华为云项目 ID（AK/SK 是项目级绑定，未配置时自动取第一个可用项目作为兜底）----
    huawei_project_id: str = _env("HW_PROJECT_ID", "")

    # ---- 高德地图 Web 服务（校园路径规划/地理编码，未配置时降级为直线距离）----
    amap_key: str = _env("AMAP_KEY", "")

    # ---- 内置管理员（固定手机号 + 初始密码，登录后请自行修改）----
    admin_phone: str = _env("ADMIN_PHONE", "13800000000")
    admin_initial_password: str = _env("ADMIN_INITIAL_PASSWORD", "Admin123")

    # ---- 邮箱 SMTP（个人中心验证码/找回密码，QQ 邮箱 smtp.qq.com 465 SSL）----
    smtp_host: str = _env("SMTP_HOST", "smtp.qq.com")
    smtp_port: int = int(_env("SMTP_PORT", "465"))
    smtp_user: str = _env("SMTP_USER", "3338542316@qq.com")
    smtp_password: str = _env("SMTP_PASSWORD", "cviyrdnsrbgkcibc")
    email_sender: str = _env("EMAIL_SENDER", "3338542316@qq.com")

    # ---- 登录令牌签名密钥（HMAC，生产请用 .env 覆盖）----
    auth_secret: str = _env("AUTH_SECRET", "campus-delivery-secret-2026")

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()