"""清空旧演示数据，用真实校园数据（致远居楼栋 + 三校门）重新生成完整演示数据。

用法（在 campus_delivery 目录下）：
    /root/venv/bin/python scripts/seed_real_orders.py
可重复运行：每次先清空业务表再重新生成。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app import models  # noqa: E402
from app.services.dispatch_service import CAMPUS_BUILDINGS, GATES  # noqa: E402

ORDER_STATUS_FLOW = ["pending", "picked", "handover", "in_campus", "arrived_site", "dorm_delivery", "delivered"]
STATUS_TO_NODE = {
    "picked": "pickup",
    "handover": "external_handover",
    "in_campus": "internal_transport",
    "arrived_site": "site_arrival",
    "dorm_delivery": "dorm_delivery",
    "delivered": "completed",
}
COURIERS = ["刘师傅", "陈师傅", "赵师傅"]
VEHICLES = ["川A·EV001", "川A·EV002"]


def _gate_for(building: str) -> tuple[str, list[float]]:
    """返回该楼栋就近的大门（校外交接点）。"""
    b = CAMPUS_BUILDINGS[building]
    return min(GATES.items(), key=lambda kv: (kv[1][0] - b[0]) ** 2 + (kv[1][1] - b[1]) ** 2)


def _node_coords(building: str, node_type: str) -> list[float]:
    """节点坐标：校外交接用大门坐标，校内节点用楼栋坐标。"""
    if node_type in ("pickup", "external_handover"):
        return _gate_for(building)[1]
    return CAMPUS_BUILDINGS[building]


def make_order(i: int, status: str, source: str, name: str, dorm: str, room: str, vendor: str, food: str) -> models.Order:
    base = datetime.now()
    lon, lat = CAMPUS_BUILDINGS[dorm]
    return models.Order(
        order_no=f"REAL{datetime.now():%m%d%H%M}{i:03d}",
        customer_name=name,
        customer_phone=f"138{10000000 + i * 137:08d}",
        dorm_building=dorm,
        dorm_room=room,
        vendor_name=vendor,
        vendor_phone=f"139{20000000 + i * 97:08d}",
        food_items=food,
        status=status,
        source=source,
        longitude=lon,
        latitude=lat,
        created_at=base - timedelta(minutes=90 - i * 4),
        expected_delivery_at=base + timedelta(minutes=30),
        delivered_at=base if status == "delivered" else None,
    )


def nodes_for(order: models.Order, status: str, start: datetime) -> list[models.DeliveryNode]:
    nodes: list[models.DeliveryNode] = []
    if status not in ORDER_STATUS_FLOW:
        return nodes
    idx = ORDER_STATUS_FLOW.index(status)
    t = start
    for k, s in enumerate(ORDER_STATUS_FLOW[1 : idx + 1], 1):
        nt = STATUS_TO_NODE[s]
        t = t + timedelta(minutes=6 * k)
        lon, lat = _node_coords(order.dorm_building, nt)
        nodes.append(
            models.DeliveryNode(
                order_id=order.id,
                node_type=nt,
                occurred_at=t,
                longitude=lon,
                latitude=lat,
                courier_name=COURIERS[k % len(COURIERS)],
                vehicle_id=VEHICLES[k % len(VEHICLES)],
                note=f"{order.order_no} 节点 {nt}",
            )
        )
    return nodes


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # 清空旧业务数据（按外键依赖顺序）
        for model in [
            models.PhotoRecord,
            models.DeliveryNode,
            models.Anomaly,
            models.NotificationSubscription,
            models.VehicleTrip,
            models.StaffShift,
            models.Order,
        ]:
            db.query(model).delete()
        db.commit()

        # 致远居订单，覆盖各状态，来源混合 manual/ocr
        rows = [
            ("pending", "ocr", "张伟", "致远居1栋", "5-302", "川味小馆", "麻辣香锅+米饭"),
            ("pending", "manual", "李娜", "致远居2栋", "3-105", "兰州拉面", "牛肉拉面+煎蛋"),
            ("picked", "ocr", "王强", "致远居3栋", "1-208", "沙县小吃", "鸡腿饭+例汤"),
            ("handover", "manual", "刘洋", "致远居4栋", "2-411", "麦当劳", "巨无霸套餐"),
            ("handover", "ocr", "陈静", "致远居1栋", "6-120", "真功夫", "香菇滑鸡饭"),
            ("in_campus", "manual", "杨帆", "致远居2栋", "7-303", "必胜客", "夏威夷披萨"),
            ("in_campus", "ocr", "赵敏", "致远居5栋", "4-216", "华莱士", "香辣鸡腿堡"),
            ("arrived_site", "manual", "孙磊", "致远居3栋", "8-508", "老北京炸酱面", "炸酱面+北冰洋"),
            ("dorm_delivery", "ocr", "周杰", "致远居6栋", "2-110", "黄焖鸡米饭", "黄焖鸡+可乐"),
            ("dorm_delivery", "manual", "吴倩", "致远居4栋", "1-305", "冒菜", "素冒菜+米饭"),
            ("delivered", "ocr", "郑爽", "致远居5栋", "5-220", "石锅拌饭", "牛肉石锅拌饭"),
            ("delivered", "manual", "冯巩", "致远居6栋", "3-404", "麻辣烫", "麻辣烫+冰红茶"),
            ("abnormal", "manual", "钱七", "致远居2栋", "6-501", "小笼包", "小笼包+豆浆"),
        ]
        orders: list[models.Order] = []
        for i, (status, source, name, dorm, room, vendor, food) in enumerate(rows, 1):
            o = make_order(i, status, source, name, dorm, room, vendor, food)
            db.add(o)
            db.flush()
            for n in nodes_for(o, status, o.created_at):
                db.add(n)
            orders.append(o)
        db.commit()

        # 异常记录
        db.add(
            models.Anomaly(
                order_id=orders[-1].id,
                anomaly_type="lost",
                reported_at=datetime.now() - timedelta(minutes=20),
                reported_by=orders[-1].customer_name,
                description="校外交接后未到寝，疑似在运输环节丢失",
                status="resolved",
                located_node_type="internal_transport",
                handle_log=[
                    {"action": "locate", "operator": "调度员", "detail": "定位到校内运输环节"},
                    {"action": "compensate", "operator": "系统", "detail": "补偿 5.0 元"},
                ],
                compensation_granted=True,
                compensation_amount=5.0,
                resolution="已补偿并重新配送",
            )
        )
        db.add(
            models.Anomaly(
                order_id=orders[-3].id,
                anomaly_type="not_delivered",
                reported_at=datetime.now() - timedelta(minutes=8),
                reported_by=orders[-3].customer_name,
                description="显示已到寝但本人未收到",
                status="investigating",
                handle_log=[{"action": "investigate", "operator": "配送员", "detail": "正在核查到寝交付记录"}],
            )
        )

        # 人力分配：致远居各楼栋
        for dorm, name, cnt in [("致远居1栋", "小马", 4), ("致远居2栋", "小何", 3), ("致远居3栋", "小杨", 2)]:
            db.add(
                models.StaffShift(
                    dorm_building=dorm,
                    shift_time="晚班 17:00-21:00",
                    courier_name=name,
                    order_count=cnt,
                    time_window="17:00-21:00",
                )
            )

        # 订阅
        db.add(models.NotificationSubscription(order_id=orders[-3].id, channel="app_push", contact=orders[-3].customer_name))
        db.add(models.NotificationSubscription(order_id=None, channel="sms", contact="食堂管理员"))
        db.commit()

        print("✅ 真实校园演示数据已生成：")
        print(f"   订单 {len(orders)} 个（致远居1-6栋，覆盖各状态，来源手动/OCR 混合）")
        print(f"   轨迹节点 {db.query(models.DeliveryNode).count()} 条")
        print(f"   异常 {db.query(models.Anomaly).count()} 条")
        print(f"   人力分配 {db.query(models.StaffShift).count()} 人、订阅 {db.query(models.NotificationSubscription).count()} 条")
        print("   校门（三选一就近分配）：一号门 / 西门 / 西北门")
        print("   到「统筹调度」页点「规划调度」即可看到真实致远居路线。")
    finally:
        db.close()


if __name__ == "__main__":
    main()