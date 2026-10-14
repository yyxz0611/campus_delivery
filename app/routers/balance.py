"""虚拟余额路由：流水查询 + 管理员充值。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..security import parse_token
from ..services import balance_service

router = APIRouter(prefix="/api/balance", tags=["balance"])


@router.get("/transactions")
def transactions(limit: int = 50, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if not current:
        raise HTTPException(401, "未登录")
    return balance_service.list_transactions(db, current[0], limit)


@router.post("/recharge")
def recharge(payload: schemas.RechargeRequest, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if not current or current[1] != "admin":
        raise HTTPException(403, "仅管理员可充值")
    try:
        txn = balance_service.recharge(db, payload.user_id, payload.amount, payload.description)
        return balance_service._to_dict(txn)
    except ValueError as e:
        raise HTTPException(400, str(e))