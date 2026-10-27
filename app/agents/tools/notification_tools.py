# -*- coding: utf-8 -*-
"""AI 助手的通知工具：把 2.0 的 notification_service 包装为 LLM 可调用的 @tool。

消息会落到目标用户的「通知中心」（notifications 表 + Redis 实时推送），
复用 2.0 的通知可见性模型（target_role 广播 / target_user_id 定向）。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool
from sqlalchemy import select

from ... import models
from ...services import notification_service, order_service
from ..context import get_current_user, get_db

ROLES = ("admin", "rider", "student")
ROLE_NAMES = {"admin": "管理员", "rider": "骑手", "student": "学生"}


@tool
def send_notification(target: str, title: str, content: str, order_no: str = "") -> str:
    """向目标发送一条通知，消息会出现在对方 App 的「通知中心」里。

    参数：
    - target：通知目标。填 "admin" / "rider" / "student" 表示按角色通知该角色所有人；
      填 "user:13800138000" 表示只通知该手机号对应的用户。
    - title：通知标题，一句话概括。
    - content：通知正文，把要告知对方的内容写清楚（不要编造订单号、金额、承诺）。
    - order_no：关联的订单号（可选）。填写时会校验当前身份是否有权访问该订单。

    权限规则：
    - 管理员可以通知任意角色或指定用户；
    - 学生与骑手只能向管理员（admin）发送通知。
    """
    db = get_db()
    current = get_current_user()
    if current is None:
        return "未获取到登录身份，无法发送通知。"
    uid, role = current

    target = (target or "").strip()
    title = (title or "").strip()
    content = (content or "").strip()
    if not target:
        return "缺少通知目标，请指定 admin / rider / student 或 user:手机号。"
    if not title:
        return "缺少通知标题。"

    target_role: str | None = None
    target_user_id: int | None = None
    target_desc = ""

    if target.lower().startswith("user:"):
        phone = target.split(":", 1)[1].strip()
        if role != "admin":
            return "只有管理员可以定向通知到具体用户，你只能向管理员发送通知。"
        user = db.scalar(select(models.User).where(models.User.phone == phone))
        if user is None:
            return f"未找到手机号 {phone} 对应的用户，请核对后重试。"
        target_user_id = user.id
        target_desc = f"用户 {user.name}（{phone}）"
    else:
        key = target.lower()
        if key not in ROLES:
            return f"无法识别的通知目标「{target}」，请使用 admin / rider / student 或 user:手机号。"
        if role != "admin" and key != "admin":
            return "学生与骑手只能向管理员发送通知，不能直接通知其他角色。"
        target_role = key
        target_desc = f"全部{ROLE_NAMES[key]}"

    order_id: int | None = None
    if order_no:
        order = order_service.get_order_by_no(db, order_no.strip())
        if order is None:
            return f"未找到订单 {order_no}，通知未发送。"
        if not _can_access_order(db, order, current):
            return f"你无权访问订单 {order_no}，通知未发送。"
        order_id = order.id

    payload = notification_service.notify(
        db,
        order_id=order_id,
        title=title[:128],
        content=content,
        channel="app_push",
        target_role=target_role,
        target_user_id=target_user_id,
    )
    return json.dumps(
        {
            "notification_id": payload["id"],
            "target": target_desc,
            "title": title[:128],
            "sent": True,
            "message": f"通知已发送到{target_desc}的通知中心",
        },
        ensure_ascii=False,
    )


def _can_access_order(db, order: models.Order, current: tuple[int, str] | None) -> bool:
    """复用 2.0 订单权限模型：学生按寝室+姓名、骑手按 rider_user_id、管理员全局。"""
    if current is None:
        return False
    uid, role = current
    if role == "admin":
        return True
    if role == "rider":
        return order.rider_user_id == uid
    if role == "student":
        user = db.get(models.User, uid)
        if user is None:
            return False
        return (
            user.dorm_building == order.dorm_building
            and user.dorm_room == order.dorm_room
            and user.name == order.customer_name
        )
    return False


NOTIFICATION_TOOLS = [send_notification]