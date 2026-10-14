"""登录/身份服务：一个自然人（手机号唯一）可有多个角色，每个角色一套独立密码。"""
from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import string
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..redis_client import redis_client
from . import email_service

VALID_ROLES = {"admin", "rider", "student"}
SIGNUP_ROLES = {"rider", "student"}

ROLE_LABELS = {"admin": "管理员", "rider": "骑手", "student": "学生"}

_PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{6,12}$")


def _password_ok(password: str) -> bool:
    return bool(_PASSWORD_RE.match(password or ""))


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return f"{salt}${digest}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return calc == digest


def _ensure_password_unique(user: models.User, new_password: str, exclude_role: str = "") -> None:
    """一个密码只能对应一个身份：校验新密码不与该用户其他角色的密码相同。"""
    for c in user.credentials:
        if c.role != exclude_role and c.password_hash and _verify_password(new_password, c.password_hash):
            raise ValueError("该密码已被其他身份使用，一个密码只能对应一个身份")


def _match_role(user: models.User, password: str) -> str | None:
    for cred in user.credentials:
        if cred.password_hash and _verify_password(password, cred.password_hash):
            return cred.role
    return None


def to_dict(user: models.User, role: str, token: str | None = None) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "phone": user.phone,
        "email": user.email,
        "role": role,
        "balance": user.balance,
        "dorm_building": user.dorm_building or "",
        "dorm_room": user.dorm_room or "",
        "token": token,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def login(db: Session, phone: str, password: str) -> tuple[models.User, str]:
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("手机号不能为空")
    if not re.fullmatch(r"\d{11}", phone):
        raise ValueError("手机号必须为 11 位数字")
    if not password:
        raise ValueError("密码不能为空")

    user = db.scalar(select(models.User).where(models.User.phone == phone))
    if user is None:
        raise ValueError("该手机号未注册")
    role = _match_role(user, password)
    if role is None:
        raise ValueError("密码错误")

    user.last_login_at = datetime.now()
    db.commit()
    db.refresh(user)
    return user, role


def register(db: Session, name: str, phone: str, email: str, password: str, role: str) -> tuple[models.User, str]:
    name = (name or "").strip()
    phone = (phone or "").strip()
    email = (email or "").strip()
    if not name or not phone or not email:
        raise ValueError("姓名、手机号和邮箱均不能为空")
    if not re.fullmatch(r"\d{11}", phone):
        raise ValueError("手机号必须为 11 位数字")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("邮箱格式不正确")
    if role not in SIGNUP_ROLES:
        raise ValueError("仅支持注册骑手或学生身份")
    if not _password_ok(password):
        raise ValueError("密码需为 6-12 位，且只能包含大小写字母和数字")

    user = db.scalar(select(models.User).where(models.User.phone == phone))
    if user is None:
        user = models.User(name=name, phone=phone, email=email)
        db.add(user)
        db.flush()
    else:
        user.name = name
        if not user.email:
            user.email = email

    if any(c.role == role for c in user.credentials):
        raise ValueError(f"该手机号已注册过「{ROLE_LABELS.get(role, role)}」身份")

    _ensure_password_unique(user, password)
    db.add(models.UserCredential(user_id=user.id, role=role, password_hash=_hash_password(password)))
    user.last_login_at = datetime.now()
    db.commit()
    db.refresh(user)
    return user, role


def ensure_builtin_admin(db: Session, phone: str, password: str) -> None:
    """确保存在内置管理员账号（幂等）。"""
    user = db.scalar(select(models.User).where(models.User.phone == phone))
    if user is None:
        user = models.User(name="管理员", phone=phone)
        db.add(user)
        db.flush()
    if not any(c.role == "admin" for c in user.credentials):
        db.add(models.UserCredential(user_id=user.id, role="admin", password_hash=_hash_password(password)))
    db.commit()

# ---- 邮箱验证码 ----
CODE_TTL = 300


def _code_key(email: str) -> str:
    return f"email_code:{email}"


def send_code(email: str) -> None:
    email = (email or "").strip()
    if not email:
        raise ValueError("邮箱不能为空")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("邮箱格式不正确")
    code = "".join(random.choices(string.digits, k=6))
    redis_client.set(_code_key(email), code, ttl=CODE_TTL)
    email_service.send_verification_code(email, code)


def _verify_code(email: str, code: str) -> bool:
    raw = redis_client.get(_code_key((email or "").strip()))
    if not raw:
        return False
    try:
        stored = json.loads(raw)
    except (ValueError, TypeError):
        stored = raw
    return stored == code


def _get_credential(user: models.User, role: str) -> models.UserCredential | None:
    return next((c for c in user.credentials if c.role == role), None)


def change_password(db: Session, phone: str, role: str, old_password: str, new_password: str) -> None:
    phone = (phone or "").strip()
    if not _password_ok(new_password):
        raise ValueError("新密码需为 6-12 位，且只能包含大小写字母和数字")
    user = db.scalar(select(models.User).where(models.User.phone == phone))
    if user is None:
        raise ValueError("该手机号未注册")
    cred = _get_credential(user, role)
    if cred is None:
        raise ValueError(f"该账号未绑定「{ROLE_LABELS.get(role, role)}」身份")
    if not cred.password_hash or not _verify_password(old_password, cred.password_hash):
        raise ValueError("旧密码错误")
    _ensure_password_unique(user, new_password, exclude_role=role)
    cred.password_hash = _hash_password(new_password)
    db.commit()


def delete_account(db: Session, user_id: int, password: str) -> None:
    """注销账号：验证密码后删除整个用户（含所有角色凭据），并解除骑手订单关联。"""
    user = db.get(models.User, user_id)
    if user is None:
        raise ValueError("用户不存在")
    role = _match_role(user, password)
    if role is None:
        raise ValueError("密码错误")
    if role == "admin":
        raise ValueError("管理员账号不可注销")
    from sqlalchemy import update
    db.execute(update(models.Order).where(models.Order.rider_user_id == user.id).values(rider_user_id=None))
    db.delete(user)
    db.commit()


def update_profile(db: Session, phone: str, role: str, password: str, name: str | None, email: str | None, email_code: str | None, dorm_building: str | None = None, dorm_room: str | None = None) -> models.User:
    phone = (phone or "").strip()
    user = db.scalar(select(models.User).where(models.User.phone == phone))
    if user is None:
        raise ValueError("该手机号未注册")
    cred = _get_credential(user, role)
    if cred is None or not _verify_password(password, cred.password_hash):
        raise ValueError("密码错误")

    if name is not None and name.strip():
        user.name = name.strip()

    new_email = (email or "").strip() if email is not None else None
    if new_email is not None and new_email != user.email:
        if not _verify_code(new_email, email_code):
            raise ValueError("邮箱验证码错误或已过期")
        user.email = new_email

    if dorm_building is not None:
        user.dorm_building = dorm_building.strip()
    if dorm_room is not None:
        user.dorm_room = dorm_room.strip()

    db.commit()
    db.refresh(user)
    return user


def reset_password(db: Session, email: str, code: str, role: str, new_password: str) -> None:
    email = (email or "").strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("邮箱格式不正确")
    if role not in VALID_ROLES:
        raise ValueError(f"非法角色：{role}")
    if not _password_ok(new_password):
        raise ValueError("新密码需为 6-12 位，且只能包含大小写字母和数字")
    if not _verify_code(email, code):
        raise ValueError("验证码错误或已过期")

    user = db.scalar(select(models.User).where(models.User.email == email))
    if user is None:
        raise ValueError("该邮箱未绑定任何账号")
    cred = _get_credential(user, role)
    if cred is None:
        raise ValueError(f"该邮箱账号下无「{ROLE_LABELS.get(role, role)}」身份")
    _ensure_password_unique(user, new_password, exclude_role=role)
    cred.password_hash = _hash_password(new_password)
    db.commit()