"""业务常量：节点类型、订单状态、异常状态等中英文映射。"""
from __future__ import annotations

NODE_TYPES = [
    "pickup",
    "external_handover",
    "internal_transport",
    "site_arrival",
    "dorm_delivery",
    "completed",
]

NODE_LABELS = {
    "pickup": "商家取餐",
    "external_handover": "校外交接",
    "internal_transport": "校内运输",
    "site_arrival": "到达楼下站点",
    "dorm_delivery": "到寝交付",
    "completed": "配送完成",
}

# 订单状态流转顺序（索引越大越靠后）
ORDER_STATUS_FLOW = ["pending", "picked", "handover", "in_campus", "arrived_site", "dorm_delivery", "delivered"]

ORDER_LABELS = {
    "pending": "待配送",
    "picked": "已取餐",
    "handover": "已交接",
    "in_campus": "校内运输中",
    "arrived_site": "已达楼下站点",
    "dorm_delivery": "配送中",
    "delivered": "已到寝完成",
    "cancelled": "已取消",
    "abnormal": "异常",
}

ANOMALY_TYPES = {
    "lost": "外卖丢失",
    "not_delivered": "未配送到寝",
}

ANOMALY_STATUS = {
    "pending": "待处理",
    "investigating": "核查中",
    "located": "已定位环节",
    "compensated": "已补偿",
    "resolved": "已解决",
}

# 订单状态 -> 轨迹节点类型
STATUS_TO_NODE = {
    "picked": "pickup",
    "handover": "external_handover",
    "in_campus": "internal_transport",
    "arrived_site": "site_arrival",
    "dorm_delivery": "dorm_delivery",
    "delivered": "completed",
}

# 需要拍照上传的关键节点
PHOTO_REQUIRED_NODES = {"external_handover", "dorm_delivery"}

CHANNELS = {"app_push": "APP推送", "sms": "短信", "inapp": "站内消息"}