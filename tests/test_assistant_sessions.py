# -*- coding: utf-8 -*-
"""AI 助手「按角色隔离会话」与「向通知中心发消息」的单测。"""
from __future__ import annotations

from app.agents.context import reset_context, set_context
from app.agents.tools.notification_tools import send_notification
from app.database import SessionLocal
from app.models import Notification, User
from app.routers.assistant import resolve_thread_id
from app.services import notification_service

STUDENT_PHONE = "13800009991"
RIDER_PHONE = "13800009992"


def _ensure_user(db, phone: str, name: str, role: str) -> int:
    user = db.query(User).filter(User.phone == phone).first()
    if user is None:
        user = User(name=name, phone=phone, email="", balance=0.0)
        db.add(user)
        db.commit()
        db.refresh(user)
    from app import models

    exists = db.query(models.UserCredential).filter(
        models.UserCredential.user_id == user.id, models.UserCredential.role == role
    ).first()
    if exists is None:
        db.add(models.UserCredential(user_id=user.id, role=role, password_hash="x"))
        db.commit()
    return user.id


# ---------------- 会话隔离 ----------------

def test_thread_id_isolated_by_role():
    admin = resolve_thread_id((7, "admin"), None)
    rider = resolve_thread_id((7, "rider"), None)
    student = resolve_thread_id((7, "student"), None)
    assert len({admin, rider, student}) == 3


def test_thread_id_isolated_by_user():
    assert resolve_thread_id((7, "student"), None) != resolve_thread_id((8, "student"), None)


def test_thread_id_accepts_own_suffix():
    assert resolve_thread_id((7, "student"), "7_student_1710000000000") == "7_student_1710000000000"


def test_thread_id_rejects_other_user_thread():
    """不能通过伪造 thread_id 读取别人的会话。"""
    assert resolve_thread_id((8, "student"), "7_student") == "8_student"


def test_thread_id_rejects_other_role_thread():
    assert resolve_thread_id((7, "admin"), "7_student_1") == "7_admin"


def test_thread_id_rejects_prefix_confusion():
    """uid=1 的会话前缀不能匹配 uid=11。"""
    assert resolve_thread_id((1, "admin"), "11_admin") == "1_admin"
    assert resolve_thread_id((11, "admin"), "1_admin") == "11_admin"


# ---------------- 通知工具 ----------------

def test_student_can_notify_admin():
    db = SessionLocal()
    try:
        uid = _ensure_user(db, STUDENT_PHONE, "测试学生", "student")
        tokens = set_context(db, (uid, "student"))
        try:
            res = send_notification.invoke(
                {"target": "admin", "title": "订单异常", "content": "我的餐一直没送到"}
            )
        finally:
            reset_context(tokens)
        assert '"sent": true' in res
        rows = (
            db.query(Notification)
            .filter(Notification.target_role == "admin")
            .order_by(Notification.id.desc())
            .first()
        )
        assert rows is not None
        assert rows.title == "订单异常"
    finally:
        db.close()


def test_student_cannot_notify_other_role():
    db = SessionLocal()
    try:
        uid = _ensure_user(db, STUDENT_PHONE, "测试学生", "student")
        tokens = set_context(db, (uid, "student"))
        try:
            res = send_notification.invoke(
                {"target": "rider", "title": "测试", "content": "内容"}
            )
        finally:
            reset_context(tokens)
        assert "只能向管理员" in res
    finally:
        db.close()


def test_student_cannot_notify_specific_user():
    db = SessionLocal()
    try:
        uid = _ensure_user(db, STUDENT_PHONE, "测试学生", "student")
        tokens = set_context(db, (uid, "student"))
        try:
            res = send_notification.invoke(
                {"target": f"user:{RIDER_PHONE}", "title": "测试", "content": "内容"}
            )
        finally:
            reset_context(tokens)
        assert "只有管理员" in res
    finally:
        db.close()


def test_admin_can_notify_specific_user_and_is_visible_to_them():
    db = SessionLocal()
    try:
        admin_id = _ensure_user(db, "13800009990", "测试管理员", "admin")
        student_id = _ensure_user(db, STUDENT_PHONE, "测试学生", "student")
        tokens = set_context(db, (admin_id, "admin"))
        try:
            res = send_notification.invoke(
                {
                    "target": f"user:{STUDENT_PHONE}",
                    "title": "处理进度",
                    "content": "已安排骑手重新配送",
                }
            )
        finally:
            reset_context(tokens)
        assert '"sent": true' in res
        history = notification_service.history(db, role="student", user_id=student_id)
        assert any(h["title"] == "处理进度" for h in history)
        # 骑手不应看到定向给学生的通知
        rider_history = notification_service.history(db, role="rider", user_id=None)
        assert not any(h["title"] == "处理进度" for h in rider_history)
    finally:
        db.close()


def test_notify_rejects_unknown_target():
    db = SessionLocal()
    try:
        admin_id = _ensure_user(db, "13800009990", "测试管理员", "admin")
        tokens = set_context(db, (admin_id, "admin"))
        try:
            res = send_notification.invoke(
                {"target": "外星人", "title": "测试", "content": "内容"}
            )
        finally:
            reset_context(tokens)
        assert "无法识别" in res
    finally:
        db.close()


def test_notify_rejects_unknown_phone():
    db = SessionLocal()
    try:
        admin_id = _ensure_user(db, "13800009990", "测试管理员", "admin")
        tokens = set_context(db, (admin_id, "admin"))
        try:
            res = send_notification.invoke(
                {"target": "user:13000000000", "title": "测试", "content": "内容"}
            )
        finally:
            reset_context(tokens)
        assert "未找到手机号" in res
    finally:
        db.close()

def test_send_notification_is_registered_as_agent_tool():
    """通知工具必须挂到异常应急 Agent 的工具列表上，否则模型调不到。"""
    from app.agents.agents.anomaly_agent import AGENT_TOOLS

    names = [getattr(t, "name", "") for t in AGENT_TOOLS]
    assert "send_notification" in names
    assert "query_order_log" in names
    assert "report_anomaly" in names