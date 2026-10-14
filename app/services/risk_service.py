"""异常风险预测：基于可解释规则（停留时长、超时、历史异常）为订单打分并输出风险等级。

演示级"轻 AI"：无需训练模型，用规则对未来配送风险做预判，输出可解释的原因列表。
"""
from __future__ import annotations

from datetime import datetime

from .. import models


def assess_risk(order: models.Order, has_anomaly: bool = False) -> dict:
    """计算订单风险。返回 {score, level, label, reasons}，score 0-100，level 为 low/medium/high。"""
    now = datetime.now()
    reasons: list[str] = []
    score = 0

    # 终态无风险
    if order.status in ("delivered", "cancelled"):
        return {"score": 0, "level": "low", "label": "低", "reasons": ["已进入终态，无配送风险"]}

    # 1. 停留时长：卡在最后环节多久未推进
    last_time = order.nodes[-1].occurred_at if order.nodes else order.created_at
    if last_time is not None:
        idle_min = (now - last_time).total_seconds() / 60
        if idle_min >= 30:
            score += 30
            reasons.append(f"最后环节已停留 {int(idle_min)} 分钟未推进")
        elif idle_min >= 15:
            score += 20
            reasons.append(f"最后环节已停留 {int(idle_min)} 分钟")
        elif idle_min >= 5:
            score += 10
            reasons.append(f"最后环节已停留 {int(idle_min)} 分钟")

    # 2. 超时 / 临近超时
    if order.expected_delivery_at is not None:
        remain_min = (order.expected_delivery_at - now).total_seconds() / 60
        if remain_min < 0:
            score += 40
            reasons.append("已超过预计送达时间")
        elif remain_min < 10:
            score += 20
            reasons.append("临近预计送达时间（不足 10 分钟）")

    # 3. 异常信号（权重最高）
    if order.status == "abnormal":
        score = 100
        reasons.append("该订单已发生异常")
    elif has_anomaly:
        score += 30
        reasons.append("该订单存在异常记录")

    score = max(0, min(score, 100))
    if score >= 60:
        level, label = "high", "高"
    elif score >= 20:
        level, label = "medium", "中"
    else:
        level, label = "low", "低"

    if not reasons:
        reasons.append("当前配送推进正常")

    return {"score": score, "level": level, "label": label, "reasons": reasons}