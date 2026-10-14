"""通知路由：历史查询 + 已读/删除管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..security import parse_token
from ..services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.post("/subscribe", response_model=schemas.SubscriptionOut)
def subscribe(payload: schemas.SubscriptionCreate, db: Session = Depends(get_db)):
    return notification_service.subscribe(db, payload.order_id, payload.channel, payload.contact)


@router.get("/subscriptions")
def subscriptions(order_id: int | None = None, db: Session = Depends(get_db)):
    return [
        {
            "id": s.id,
            "order_id": s.order_id,
            "channel": s.channel,
            "contact": s.contact,
            "active": s.active,
            "subscribed_at": s.subscribed_at.isoformat(),
        }
        for s in notification_service.list_subscriptions(db, order_id)
    ]


@router.get("/history")
def history(limit: int = 50, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    role = current[1] if current else None
    user_id = current[0] if current else None
    return notification_service.history(db, limit, role=role, user_id=user_id)


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if not current:
        raise HTTPException(401, "未登录")
    notification_service.mark_read(db, notification_id, current[0])
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if not current:
        raise HTTPException(401, "未登录")
    count = notification_service.mark_all_read(db, current[0], role=current[1])
    return {"ok": True, "count": count}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if not current:
        raise HTTPException(401, "未登录")
    notification_service.delete_notification(db, notification_id, current[0])
    return {"ok": True}


@router.post("/test")
def test_notify(db: Session = Depends(get_db), order_id: int | None = None):
    return notification_service.notify(db, order_id, "测试通知", "这是一条测试推送", "app_push")