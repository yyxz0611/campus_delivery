"""异常应急处理：上报 -> 定位配送环节 -> 核查 -> 超时补偿 -> 闭环解决。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import settings
from ..constants import ANOMALY_STATUS, ANOMALY_TYPES, NODE_LABELS, NODE_TYPES, ORDER_LABELS
from . import notification_service, tracking_service


def report_anomaly(
    db: Session,
    payload: schemas.AnomalyCreate,
    reported_by_user_id: int | None = None,
    reported_role: str = "",
) -> models.Anomaly:
    order = db.get(models.Order, payload.order_id)
    if order is None:
        raise ValueError(f"订单 {payload.order_id} 不存在")

    reporter = payload.reported_by or ""
    anomaly = models.Anomaly(
        order_id=payload.order_id,
        anomaly_type=payload.anomaly_type,
        reported_at=datetime.now(),
        reported_by=reporter,
        reported_by_user_id=reported_by_user_id,
        reported_role=reported_role,
        description=payload.description,
        status="pending",
        handle_log=[
            {
                "action": "上报异常",
                "operator": reporter or "用餐人",
                "detail": f"提出{ANOMALY_TYPES.get(payload.anomaly_type, payload.anomaly_type)}",
                "ts": datetime.now().isoformat(),
            }
        ],
    )
    db.add(anomaly)
    order.status = "abnormal"
    db.commit()
    db.refresh(anomaly)

    notification_service.notify(
        db, order.id, "异常上报", f"订单 {order.order_no} 已被上报异常（上报人：{reporter or '用餐人'}），等待相关负责人核查", target_role="admin"
    )
    return anomaly


def locate_anomaly(db: Session, anomaly_id: int) -> models.Anomaly:
    """基于订单轨迹，定位问题出现在哪个配送环节。"""
    anomaly = db.get(models.Anomaly, anomaly_id)
    if anomaly is None:
        raise ValueError("异常不存在")

    nodes = tracking_service.get_trajectory(db, anomaly.order_id)
    if not nodes:
        located = NODE_TYPES[0]
    else:
        last_type = nodes[-1]["node_type"]
        last_idx = NODE_TYPES.index(last_type) if last_type in NODE_TYPES else 0
        located = NODE_TYPES[min(last_idx + 1, len(NODE_TYPES) - 1)]

    anomaly.located_node_type = located
    anomaly.status = "located"
    anomaly.handle_log.append(
        {
            "action": "定位环节",
            "operator": "系统",
            "detail": f"问题定位在「{NODE_LABELS.get(located, located)}」环节",
            "ts": datetime.now().isoformat(),
        }
    )
    db.commit()
    db.refresh(anomaly)

    order = db.get(models.Order, anomaly.order_id)
    if order:
        notification_service.notify_for_rider(
            db, order, "异常核查", f"订单 {order.order_no} 异常已定位在「{NODE_LABELS.get(located, located)}」环节，请核实该环节情况"
        )
    return anomaly


def add_handle_log(db: Session, anomaly_id: int, action: str, operator: str, detail: str) -> models.Anomaly:
    anomaly = db.get(models.Anomaly, anomaly_id)
    if anomaly is None:
        raise ValueError("异常不存在")
    anomaly.handle_log.append(
        {"action": action, "operator": operator, "detail": detail, "ts": datetime.now().isoformat()}
    )
    if action == "核实中":
        anomaly.status = "investigating"
    db.commit()
    db.refresh(anomaly)

    order = db.get(models.Order, anomaly.order_id)
    if order:
        if action == "联系骑手":
            notification_service.notify_for_rider(db, order, "联系骑手", detail or f"订单 {order.order_no} 异常需核实")
        elif action == "反馈学生":
            notification_service.notify_for_order(db, order, "处理反馈", detail or f"订单 {order.order_no} 异常处理结果已反馈")
    return anomaly


def compensate(db: Session, anomaly_id: int, amount: float | None = None) -> models.Anomaly:
    """超时无进度 -> 给予补偿 + 退款/反馈解决方式，自动入账到学生虚拟余额。"""
    from . import balance_service

    anomaly = db.get(models.Anomaly, anomaly_id)
    if anomaly is None:
        raise ValueError("异常不存在")
    order = db.get(models.Order, anomaly.order_id)

    anomaly.compensation_granted = True
    anomaly.compensation_amount = amount if amount is not None else settings.compensation_amount
    anomaly.resolution = f"给予用餐人 {anomaly.compensation_amount} 元补偿，并原路退款；已反馈用户处理结果"
    anomaly.status = "compensated"
    anomaly.handle_log.append(
        {
            "action": "触发补偿",
            "operator": "系统",
            "detail": anomaly.resolution,
            "ts": datetime.now().isoformat(),
        }
    )
    db.commit()
    db.refresh(anomaly)

    student = notification_service._find_student_user(db, order)
    if student:
        try:
            balance_service.compensate(
                db, student.id, order.id, anomaly.compensation_amount,
                f"订单 {order.order_no} 异常补偿",
            )
        except ValueError:
            pass

    notification_service.notify_for_order(
        db, order, "补偿通知", f"订单 {order.order_no} 处理超时，已补偿 {anomaly.compensation_amount} 元并退款"
    )
    return anomaly


def resolve(db: Session, anomaly_id: int, resolution: str = "") -> models.Anomaly:
    anomaly = db.get(models.Anomaly, anomaly_id)
    if anomaly is None:
        raise ValueError("异常不存在")
    anomaly.resolution = resolution or anomaly.resolution
    anomaly.status = "resolved"
    anomaly.handle_log.append(
        {"action": "闭环解决", "operator": "负责人", "detail": anomaly.resolution, "ts": datetime.now().isoformat()}
    )
    db.commit()
    db.refresh(anomaly)

    order = db.get(models.Order, anomaly.order_id)
    if order:
        notification_service.notify_for_order(
            db, order, "异常已解决", anomaly.resolution or f"订单 {order.order_no} 异常已闭环解决"
        )
    return anomaly


def check_timeouts(db: Session) -> list[models.Anomaly]:
    """扫描超过阈值仍无进度的异常，自动补偿。"""
    now = datetime.now()
    timeout_ms = settings.anomaly_timeout_seconds * 1000
    rows = db.scalars(
        select(models.Anomaly).where(models.Anomaly.status.in_(["pending", "investigating"]))
    ).all()
    triggered = []
    for a in rows:
        elapsed_ms = (now - a.reported_at).total_seconds() * 1000
        if elapsed_ms >= timeout_ms and not a.compensation_granted:
            compensate(db, a.id)
            triggered.append(a)
    return triggered


def list_anomalies(db: Session, current: tuple[int, str] | None = None) -> list[models.Anomaly]:
    stmt = select(models.Anomaly).order_by(models.Anomaly.reported_at.desc())
    if current:
        uid, role = current
        if role != "admin":
            stmt = stmt.where(models.Anomaly.reported_by_user_id == uid)
    return list(db.scalars(stmt).all())


def get_anomaly_contacts(db: Session, anomaly_id: int) -> dict | None:
    """返回异常订单关联的骑手与学生联系方式（供管理员联系确认）。"""
    anomaly = db.get(models.Anomaly, anomaly_id)
    if anomaly is None:
        return None
    order = db.get(models.Order, anomaly.order_id)
    if order is None:
        return {"anomaly_id": anomaly_id, "rider": None, "student": None, "order_no": ""}

    rider = None
    if order.rider_user_id:
        r = db.get(models.User, order.rider_user_id)
        if r:
            rider = {"id": r.id, "name": r.name, "phone": r.phone, "email": r.email or ""}

    student = None
    if order.dorm_building and order.dorm_room and order.customer_name:
        s = db.scalar(
            select(models.User).where(
                models.User.dorm_building == order.dorm_building,
                models.User.dorm_room == order.dorm_room,
                models.User.name == order.customer_name,
            )
        )
        if s:
            student = {"id": s.id, "name": s.name, "phone": s.phone, "email": s.email or ""}

    return {
        "anomaly_id": anomaly_id,
        "order_no": order.order_no,
        "rider": rider,
        "student": student,
    }


def to_dict(a: models.Anomaly) -> dict:
    order = None
    return {
        "id": a.id,
        "order_id": a.order_id,
        "anomaly_type": a.anomaly_type,
        "anomaly_type_label": ANOMALY_TYPES.get(a.anomaly_type, a.anomaly_type),
        "reported_at": a.reported_at.isoformat(),
        "reported_by": a.reported_by,
        "reported_role": a.reported_role,
        "description": a.description,
        "status": a.status,
        "status_label": ANOMALY_STATUS.get(a.status, a.status),
        "located_node_type": a.located_node_type,
        "located_node_label": NODE_LABELS.get(a.located_node_type, a.located_node_type) if a.located_node_type else None,
        "handle_log": a.handle_log,
        "compensation_granted": a.compensation_granted,
        "compensation_amount": a.compensation_amount,
        "resolution": a.resolution,
    }