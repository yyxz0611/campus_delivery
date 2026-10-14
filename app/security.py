"""登录令牌：HMAC 签名，不可伪造。格式 uid.role.exp.sig。"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

from .config import settings

_TTL = 7 * 24 * 3600


def make_token(user_id: int, role: str, ttl: int = _TTL) -> str:
    exp = int(time.time()) + ttl
    payload = f"{user_id}.{role}.{exp}"
    sig = hmac.new(settings.auth_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def parse_token(token: str | None) -> Optional[tuple[int, str]]:
    if not token:
        return None
    try:
        uid_s, role, exp_s, sig = token.split(".")
        payload = f"{uid_s}.{role}.{exp_s}"
        expected = hmac.new(settings.auth_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_s) < time.time():
            return None
        return int(uid_s), role
    except (ValueError, TypeError):
        return None