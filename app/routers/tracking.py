"""轨迹与日志路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import tracking_service

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


@router.get("/{order_id}")
def trajectory(order_id: int, db: Session = Depends(get_db)):
    return tracking_service.get_trajectory(db, order_id)


@router.post("/nodes")
def add_node(payload: schemas.NodeCreate, db: Session = Depends(get_db)):
    node = tracking_service.add_node(
        db,
        payload.order_id,
        payload.node_type,
        lon=payload.longitude,
        lat=payload.latitude,
        courier=payload.courier_name,
        vehicle=payload.vehicle_id,
        note=payload.note,
        occurred_at=payload.occurred_at,
    )
    return {"id": node.id, "node_type": node.node_type}


@router.get("/log/{order_no}")
def full_log(order_no: str, db: Session = Depends(get_db)):
    log = tracking_service.full_log(db, order_no)
    if not log:
        raise HTTPException(404, "订单不存在")
    return log