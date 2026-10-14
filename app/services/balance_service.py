"""虚拟余额服务：充值/补偿/退款/消费 + 流水查询。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models

TXN_TYPES = {"recharge": "充值", "compensation": "补偿入账", "refund": "退款", "consume": "消费"}


def _apply(db: Session, user_id: int, order_id: int | None, txn_type: str, amount: float, description: str) -> models.BalanceTransaction:
    user = db.get(models.User, user_id)
    if user is None:
        raise ValueError("用户不存在")
    user.balance = round(user.balance + amount, 2)
    txn = models.BalanceTransaction(
        user_id=user_id,
        order_id=order_id,
        type=txn_type,
        amount=round(amount, 2),
        balance_after=user.balance,
        description=description,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def recharge(db: Session, user_id: int, amount: float, description: str = "") -> models.BalanceTransaction:
    if amount <= 0:
        raise ValueError("充值金额必须大于 0")
    return _apply(db, user_id, None, "recharge", amount, description or "管理员充值")


def compensate(db: Session, user_id: int, order_id: int, amount: float, description: str = "") -> models.BalanceTransaction:
    if amount <= 0:
        raise ValueError("补偿金额必须大于 0")
    return _apply(db, user_id, order_id, "compensation", amount, description or "异常补偿入账")


def refund(db: Session, user_id: int, order_id: int, amount: float, description: str = "") -> models.BalanceTransaction:
    if amount <= 0:
        raise ValueError("退款金额必须大于 0")
    return _apply(db, user_id, order_id, "refund", amount, description or "订单退款")


def consume(db: Session, user_id: int, order_id: int, amount: float, description: str = "") -> models.BalanceTransaction:
    if amount <= 0:
        raise ValueError("消费金额必须大于 0")
    user = db.get(models.User, user_id)
    if user and user.balance < amount:
        raise ValueError("余额不足")
    return _apply(db, user_id, order_id, "consume", -amount, description or "订单消费")


def list_transactions(db: Session, user_id: int, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(models.BalanceTransaction)
        .where(models.BalanceTransaction.user_id == user_id)
        .order_by(models.BalanceTransaction.created_at.desc())
        .limit(limit)
    ).all()
    return [_to_dict(t) for t in rows]


def _to_dict(t: models.BalanceTransaction) -> dict:
    return {
        "id": t.id,
        "user_id": t.user_id,
        "order_id": t.order_id,
        "type": t.type,
        "type_label": TXN_TYPES.get(t.type, t.type),
        "amount": t.amount,
        "balance_after": t.balance_after,
        "description": t.description,
        "created_at": t.created_at.isoformat(),
    }