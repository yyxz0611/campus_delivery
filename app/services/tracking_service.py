"""轨迹服务：查询每个订单独有的配送轨迹/日志（含时间戳、经纬度、照片）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..constants import NODE_LABELS


def add_node(
    db: Session,
    order_id: int,
    node_type: str,
    lon: float | None = None,
    lat: float | None = None,
    courier: str = "",
    vehicle: str = "",
    note: str = "",
    occurred_at: datetime | None = None,
) -> models.DeliveryNode:
    node = models.DeliveryNode(
        order_id=order_id,
        node_type=node_type,
        occurred_at=occurred_at or datetime.now(),
        longitude=lon,
        latitude=lat,
        courier_name=courier,
        vehicle_id=vehicle,
        note=note,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def get_trajectory(db: Session, order_id: int) -> list[dict]:
    nodes = list(
        db.scalars(
            select(models.DeliveryNode)
            .where(models.DeliveryNode.order_id == order_id)
            .order_by(models.DeliveryNode.occurred_at.asc())
        ).all()
    )
    result = []
    for n in nodes:
        photos = [p for p in (n.photos if n.photos else [])]
        result.append(
            {
                "id": n.id,
                "node_type": n.node_type,
                "node_label": NODE_LABELS.get(n.node_type, n.node_type),
                "occurred_at": n.occurred_at.isoformat(),
                "longitude": n.longitude,
                "latitude": n.latitude,
                "courier_name": n.courier_name,
                "vehicle_id": n.vehicle_id,
                "note": n.note,
                "photos": [
                    {
                        "id": p.id,
                        "file_path": p.file_path,
                        "audit_status": p.audit_status,
                        "audit_result": p.audit_result,
                        "reject_reason": p.reject_reason,
                    }
                    for p in photos
                ],
            }
        )
    return result


def full_log(db: Session, order_no: str) -> dict:
    """返回订单完整轨迹日志（用于异常定位）。"""
    order = db.scalar(select(models.Order).where(models.Order.order_no == order_no))
    if order is None:
        return {}
    return {
        "order": {
            "id": order.id,
            "order_no": order.order_no,
            "customer_name": order.customer_name,
            "dorm_building": order.dorm_building,
            "dorm_room": order.dorm_room,
            "status": order.status,
        },
        "nodes": get_trajectory(db, order.id),
        "anomalies": _anomalies_for(db, order.id),
    }


def _anomalies_for(db: Session, order_id: int) -> list[dict]:
    rows = db.scalars(select(models.Anomaly).where(models.Anomaly.order_id == order_id)).all()
    return [
        {
            "id": a.id,
            "anomaly_type": a.anomaly_type,
            "reported_at": a.reported_at.isoformat(),
            "reported_by": a.reported_by,
            "status": a.status,
            "located_node_type": a.located_node_type,
            "handle_log": a.handle_log,
            "compensation_granted": a.compensation_granted,
            "compensation_amount": a.compensation_amount,
            "resolution": a.resolution,
        }
        for a in rows
    ]