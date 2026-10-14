"""管理员服务：人员管理（列表/详情/重置密码/解绑角色/关联订单轨迹）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from . import auth_service, order_service

ROLE_LABELS = auth_service.ROLE_LABELS


def _user_summary(u: models.User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "phone": u.phone,
        "email": u.email or "",
        "balance": u.balance,
        "roles": [c.role for c in u.credentials],
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def list_users(db: Session) -> list[dict]:
    users = list(db.scalars(select(models.User).order_by(models.User.created_at.desc())).all())
    return [_user_summary(u) for u in users]


def get_user_detail(db: Session, user_id: int) -> dict | None:
    u = db.get(models.User, user_id)
    if u is None:
        return None
    return {
        **_user_summary(u),
        "credentials": [
            {"role": c.role, "created_at": c.created_at.isoformat() if c.created_at else None}
            for c in u.credentials
        ],
    }


def reset_user_password(db: Session, user_id: int, role: str, new_password: str) -> None:
    if not auth_service._password_ok(new_password):
        raise ValueError("新密码需为 6-12 位，且只能包含大小写字母和数字")
    u = db.get(models.User, user_id)
    if u is None:
        raise ValueError("用户不存在")
    cred = next((c for c in u.credentials if c.role == role), None)
    if cred is None:
        raise ValueError(f"该用户未绑定「{ROLE_LABELS.get(role, role)}」身份")
    auth_service._ensure_password_unique(u, new_password, exclude_role=role)
    cred.password_hash = auth_service._hash_password(new_password)
    db.commit()


def delete_user(db: Session, user_id: int) -> None:
    """注销用户：删除整个用户记录（含所有角色凭据），不可删除管理员。"""
    u = db.get(models.User, user_id)
    if u is None:
        raise ValueError("用户不存在")
    if any(c.role == "admin" for c in u.credentials):
        raise ValueError("不可删除管理员账号")
    from sqlalchemy import update
    db.execute(update(models.Order).where(models.Order.rider_user_id == u.id).values(rider_user_id=None))
    db.delete(u)
    db.commit()


def remove_role(db: Session, user_id: int, role: str) -> None:
    if role == "admin":
        raise ValueError("不可解绑管理员身份")
    u = db.get(models.User, user_id)
    if u is None:
        raise ValueError("用户不存在")
    cred = next((c for c in u.credentials if c.role == role), None)
    if cred is None:
        raise ValueError(f"该用户未绑定「{ROLE_LABELS.get(role, role)}」身份")
    db.delete(cred)
    db.commit()


def user_orders(db: Session, user_id: int) -> list[dict]:
    u = db.get(models.User, user_id)
    if u is None:
        return []
    stmt = (
        select(models.Order)
        .where((models.Order.customer_phone == u.phone) | (models.Order.customer_name == u.name))
        .order_by(models.Order.created_at.desc())
    )
    orders = list(db.scalars(stmt).all())
    anomaly_ids = set(db.scalars(select(models.Anomaly.order_id)).all())
    return [order_service.to_dict(o, o.id in anomaly_ids) for o in orders]