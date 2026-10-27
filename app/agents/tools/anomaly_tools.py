# -*- coding: utf-8 -*-
"""异常应急 Agent 的工具：把 2.0 的 anomaly_service / tracking_service 包装为 LLM 可调用的 @tool。

工具签名保持简单（str/int），LLM 通过 function calling 生成参数；
工具内部通过 agent context 读取当前 db session 与登录身份，复用 2.0 权限模型。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from ... import models, schemas
from ...services import anomaly_service, order_service, tracking_service
from ..context import get_current_user, get_db


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


@tool
def query_order_log(order_no: str) -> str:
    """查询指定外卖订单号的完整配送轨迹与异常记录，用于定位问题出在哪个环节。

    当用户报告订单丢失、未送达、送错等问题时，必须先调用本工具了解订单真实状态。
    参数 order_no：外卖订单号（字符串）。
    返回：订单状态、各配送节点（时间戳/经纬度/配送员）与既有异常记录。
    """
    db = get_db()
    order = order_service.get_order_by_no(db, order_no)
    if order is None:
        return f"未找到订单 {order_no}，请核对订单号。"
    if not _can_access_order(db, order, get_current_user()):
        return "您无权查询该订单，请确认订单是否属于本人。"
    log = tracking_service.full_log(db, order_no)
    return json.dumps(log, ensure_ascii=False, default=str)


@tool
def report_anomaly(order_no: str, anomaly_type: str, description: str = "") -> str:
    """为用户上报一笔外卖配送异常。

    参数：
    - order_no：外卖订单号（字符串）
    - anomaly_type：异常类型，只能是 "lost"（外卖丢失）或 "not_delivered"（未配送到寝）
    - description：对问题的补充描述（可选）

    仅当用户明确要求上报，且已通过 query_order_log 确认订单存在时才调用。
    """
    db = get_db()
    order = order_service.get_order_by_no(db, order_no)
    if order is None:
        return f"未找到订单 {order_no}，无法上报。"
    current = get_current_user()
    if not _can_access_order(db, order, current):
        return "您无权上报该订单的异常。"
    payload = schemas.AnomalyCreate(order_id=order.id, anomaly_type=anomaly_type, description=description)
    uid, role = current if current else (None, "")
    anomaly = anomaly_service.report_anomaly(db, payload, reported_by_user_id=uid, reported_role=role)
    return json.dumps(
        {"anomaly_id": anomaly.id, "order_no": order_no, "status": anomaly.status, "message": "异常已上报，等待负责人跟进"},
        ensure_ascii=False,
    )


@tool
def list_my_anomalies() -> str:
    """查询当前登录用户上报过的异常记录列表。

    无参数。返回每笔异常的类型、上报时间、处理状态与定位环节（若有）。
    """
    db = get_db()
    current = get_current_user()
    rows = anomaly_service.list_anomalies(db, current=current)
    data = [anomaly_service.to_dict(a) for a in rows]
    return json.dumps(data, ensure_ascii=False, default=str)


ANOMALY_TOOLS = [query_order_log, report_anomaly, list_my_anomalies]