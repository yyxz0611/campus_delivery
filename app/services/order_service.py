"""订单服务：创建、批量导入、状态流转（自动生成轨迹节点）、查询。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..constants import ORDER_STATUS_FLOW, STATUS_TO_NODE
from .risk_service import assess_risk


def create_order(db: Session, payload: schemas.OrderCreate, rider_user_id: int | None = None) -> models.Order:
    data = payload.model_dump()
    if rider_user_id is not None:
        data["rider_user_id"] = rider_user_id
    order = models.Order(**data)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def batch_create(db: Session, payloads: list[schemas.OrderCreate], rider_user_id: int | None = None) -> list[models.Order]:
    orders = []
    for p in payloads:
        data = p.model_dump()
        if rider_user_id is not None:
            data["rider_user_id"] = rider_user_id
        orders.append(models.Order(**data))
    db.add_all(orders)
    db.commit()
    for o in orders:
        db.refresh(o)
    return orders


def get_order(db: Session, order_id: int) -> models.Order | None:
    return db.get(models.Order, order_id)


def get_order_by_no(db: Session, order_no: str) -> models.Order | None:
    return db.scalar(select(models.Order).where(models.Order.order_no == order_no))


def list_orders(db: Session, status: str | None = None, keyword: str | None = None, current: tuple[int, str] | None = None) -> list[models.Order]:
    stmt = select(models.Order).order_by(models.Order.created_at.desc())
    if status:
        stmt = stmt.where(models.Order.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            (models.Order.order_no.like(like))
            | (models.Order.customer_name.like(like))
            | (models.Order.dorm_building.like(like))
            | (models.Order.vendor_name.like(like))
        )
    if current:
        uid, role = current
        if role == "rider":
            stmt = stmt.where(models.Order.rider_user_id == uid)
        elif role == "student":
            user = db.get(models.User, uid)
            if user and user.dorm_building and user.dorm_room and user.name:
                stmt = stmt.where(
                    models.Order.dorm_building == user.dorm_building,
                    models.Order.dorm_room == user.dorm_room,
                    models.Order.customer_name == user.name,
                )
            else:
                return []
    return list(db.scalars(stmt).all())


def _upsert_status(db: Session, order: models.Order, status: str) -> None:
    """确保状态只前进不倒退。"""
    flow = ORDER_STATUS_FLOW
    cur_idx = flow.index(order.status) if order.status in flow else -1
    new_idx = flow.index(status) if status in flow else cur_idx
    if new_idx >= cur_idx:
        order.status = status


def update_status(
    db: Session,
    order_id: int,
    status: str,
    courier_name: str = "",
    longitude: float | None = None,
    latitude: float | None = None,
    note: str = "",
    vehicle_id: str = "",
    location_only: bool = False,
) -> models.Order:
    order = get_order(db, order_id)
    if order is None:
        raise ValueError(f"订单 {order_id} 不存在")

    _upsert_status(db, order, status)

    # 骑手上报 GPS：更新订单实时位置
    if longitude is not None and latitude is not None:
        order.longitude = longitude
        order.latitude = latitude

    # 仅上报位置：只刷新坐标，不推进状态、不写轨迹节点
    if location_only:
        db.commit()
        db.refresh(order)
        return order

    # 状态流转自动生成轨迹节点
    node_type = STATUS_TO_NODE.get(status)
    if node_type:
        db.add(
            models.DeliveryNode(
                order_id=order.id,
                node_type=node_type,
                occurred_at=datetime.now(),
                longitude=longitude,
                latitude=latitude,
                courier_name=courier_name,
                vehicle_id=vehicle_id,
                note=note,
            )
        )
        if status == "delivered":
            order.delivered_at = datetime.now()

    db.commit()
    db.refresh(order)
    return order


def to_dict(order: models.Order, has_anomaly: bool = False) -> dict:
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "dorm_building": order.dorm_building,
        "dorm_room": order.dorm_room,
        "vendor_name": order.vendor_name,
        "food_items": order.food_items,
        "status": order.status,
        "source": order.source,
        "longitude": order.longitude,
        "latitude": order.latitude,
        "rider_user_id": order.rider_user_id,
        "created_at": order.created_at.isoformat(),
        "expected_delivery_at": order.expected_delivery_at.isoformat() if order.expected_delivery_at else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "risk": assess_risk(order, has_anomaly),
    }