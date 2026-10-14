"""通知服务：持久化到数据库 + Redis 实时推送。

通知支持定向：target_role（广播给某角色）或 target_user_id（定向某用户）。
二者均为空时为全局广播。history 按当前身份过滤可见通知，按时间倒序返回。
已读/删除状态按用户独立存储（NotificationUserState）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..redis_client import redis_client

CHANNEL = "notifications"


def subscribe(db: Session, order_id: int | None, channel: str, contact: str) -> models.NotificationSubscription:
    sub = models.NotificationSubscription(order_id=order_id, channel=channel, contact=contact)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def list_subscriptions(db: Session, order_id: int | None = None) -> list[models.NotificationSubscription]:
    stmt = select(models.NotificationSubscription).where(models.NotificationSubscription.active.is_(True))
    if order_id is not None:
        stmt = stmt.where(models.NotificationSubscription.order_id == order_id)
    return list(db.scalars(stmt).all())


def notify(
    db: Session,
    order_id: int | None,
    title: str,
    content: str,
    channel: str = "app_push",
    target_role: str | None = None,
    target_user_id: int | None = None,
) -> dict:
    n = models.Notification(
        order_id=order_id,
        title=title,
        content=content,
        target_role=target_role,
        target_user_id=target_user_id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    payload = {
        "id": n.id,
        "order_id": order_id,
        "title": title,
        "content": content,
        "target_role": target_role,
        "target_user_id": target_user_id,
        "ts": n.created_at.isoformat(),
    }
    redis_client.push(CHANNEL, payload)
    return payload


def _find_student_user(db: Session, order: models.Order) -> models.User | None:
    if not order.dorm_building or not order.dorm_room or not order.customer_name:
        return None
    return db.scalar(
        select(models.User).where(
            models.User.dorm_building == order.dorm_building,
            models.User.dorm_room == order.dorm_room,
            models.User.name == order.customer_name,
        )
    )


def notify_for_order(db: Session, order: models.Order, title: str, content: str) -> None:
    """订单相关通知：定向通知学生（精确到 user）+ 管理员。"""
    student = _find_student_user(db, order)
    if student:
        notify(db, order.id, title, content, target_user_id=student.id)
    else:
        notify(db, order.id, title, content, target_role="student")
    notify(db, order.id, title, content, target_role="admin")


def notify_for_rider(db: Session, order: models.Order, title: str, content: str) -> None:
    """定向通知订单关联骑手（精确到 user）。"""
    if order.rider_user_id:
        notify(db, order.id, title, content, target_user_id=order.rider_user_id)
    else:
        notify(db, order.id, title, content, target_role="rider")


def _to_dict(n: models.Notification, is_read: bool = False) -> dict:
    return {
        "id": n.id,
        "order_id": n.order_id,
        "title": n.title,
        "content": n.content,
        "target_role": n.target_role,
        "target_user_id": n.target_user_id,
        "ts": n.created_at.isoformat(),
        "is_read": is_read,
    }


def history(db: Session, limit: int = 50, role: str | None = None, user_id: int | None = None) -> list[dict]:
    """按身份过滤可见通知，按时间倒序返回，附带当前用户的已读状态。"""
    stmt = select(models.Notification).order_by(models.Notification.created_at.desc()).limit(limit)
    rows = list(db.scalars(stmt).all())

    result = []
    for n in rows:
        tr = n.target_role
        tu = n.target_user_id
        visible = False
        if tr is None and tu is None:
            visible = True
        elif role and tr == role:
            visible = True
        elif user_id and tu == user_id:
            visible = True
        if not visible:
            continue

        is_read = False
        is_deleted = False
        if user_id:
            state = db.scalar(
                select(models.NotificationUserState).where(
                    models.NotificationUserState.notification_id == n.id,
                    models.NotificationUserState.user_id == user_id,
                )
            )
            if state:
                is_read = state.is_read
                is_deleted = state.is_deleted
        if is_deleted:
            continue
        result.append(_to_dict(n, is_read))
    return result


def _get_or_create_state(db: Session, notification_id: int, user_id: int) -> models.NotificationUserState:
    state = db.scalar(
        select(models.NotificationUserState).where(
            models.NotificationUserState.notification_id == notification_id,
            models.NotificationUserState.user_id == user_id,
        )
    )
    if state is None:
        state = models.NotificationUserState(notification_id=notification_id, user_id=user_id)
        db.add(state)
    return state


def mark_read(db: Session, notification_id: int, user_id: int) -> None:
    state = _get_or_create_state(db, notification_id, user_id)
    state.is_read = True
    state.read_at = datetime.now()
    db.commit()


def mark_all_read(db: Session, user_id: int, role: str | None = None) -> int:
    """标记当前用户所有可见通知为已读，返回标记条数。"""
    stmt = select(models.Notification)
    rows = list(db.scalars(stmt).all())
    count = 0
    for n in rows:
        tr = n.target_role
        tu = n.target_user_id
        visible = False
        if tr is None and tu is None:
            visible = True
        elif role and tr == role:
            visible = True
        elif tu == user_id:
            visible = True
        if not visible:
            continue
        state = _get_or_create_state(db, n.id, user_id)
        if not state.is_read:
            state.is_read = True
            state.read_at = datetime.now()
            count += 1
    db.commit()
    return count


def delete_notification(db: Session, notification_id: int, user_id: int) -> None:
    state = _get_or_create_state(db, notification_id, user_id)
    state.is_deleted = True
    db.commit()