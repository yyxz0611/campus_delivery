"""订单相关路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..constants import NODE_LABELS, STATUS_TO_NODE
from ..database import get_db
from ..security import parse_token
from ..services import notification_service, order_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("", response_model=schemas.OrderOut)
def create_order(payload: schemas.OrderCreate, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    if order_service.get_order_by_no(db, payload.order_no):
        raise HTTPException(400, f"订单号 {payload.order_no} 已存在")
    current = parse_token(x_auth_token)
    rider_id = current[0] if current and current[1] == "rider" else None
    order = order_service.create_order(db, payload, rider_user_id=rider_id)
    if payload.source == "manual":
        notification_service.notify(
            db,
            order.id,
            "订单手动录入提醒",
            f"订单 {order.order_no} 已手动录入（寝室 {order.dorm_room}），请核对信息",
        )
    return order


@router.post("/batch")
def batch_create(payload: schemas.OrderBatchCreate, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    rider_id = current[0] if current and current[1] == "rider" else None
    orders = order_service.batch_create(db, payload.orders, rider_user_id=rider_id)
    return {"created": len(orders), "orders": [order_service.to_dict(o) for o in orders]}


@router.get("")
def list_orders(status: str | None = None, keyword: str | None = None, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    orders = order_service.list_orders(db, status=status, keyword=keyword, current=current)
    anomaly_ids = set(db.scalars(select(models.Anomaly.order_id)).all())
    return [order_service.to_dict(o, o.id in anomaly_ids) for o in orders]


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = order_service.get_order(db, order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")
    has_anomaly = db.scalar(select(models.Anomaly.order_id).where(models.Anomaly.order_id == order_id)) is not None
    return order_service.to_dict(order, has_anomaly)


@router.patch("/{order_id}/status")
def update_status(order_id: int, payload: schemas.OrderStatusUpdate, db: Session = Depends(get_db)):
    try:
        order = order_service.update_status(
            db,
            order_id,
            payload.status,
            courier_name=payload.courier_name,
            longitude=payload.longitude,
            latitude=payload.latitude,
            note=payload.note,
            location_only=payload.location_only,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    node_type = STATUS_TO_NODE.get(payload.status)
    if node_type and not payload.location_only:
        notification_service.notify_for_order(
            db, order, "配送进度更新", f"订单 {order.order_no} 当前状态：{NODE_LABELS.get(node_type, payload.status)}"
        )
    return order_service.to_dict(order)