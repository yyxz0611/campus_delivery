"""灌入演示数据：订单、轨迹、异常、调度、订阅。

用法（在 campus_delivery 目录下）：
    python scripts/seed_demo.py
可重复运行：每次先清空业务表再重新插入。
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
VEHICLES = ["京A·EV001", "京A·EV002"]


def make_order(i: int, status: str, name: str, dorm: str, room: str, vendor: str, food: str) -> models.Order:
    base = datetime.now()
    return models.Order(
        order_no=f"FD{datetime.now():%m%d%H%M}{i:03d}",
        customer_name=name,
        customer_phone=f"138{10000000 + i * 137:08d}",
        dorm_building=dorm,
        dorm_room=room,
        vendor_name=vendor,
        vendor_phone=f"139{20000000 + i * 97:08d}",
        food_items=food,
        status=status,
        longitude=116.3010 + (i % 5) * 0.003,
        latitude=39.9060 + (i % 5) * 0.002,
        created_at=base - timedelta(minutes=90 - i * 4),
        expected_delivery_at=base + timedelta(minutes=30),
        delivered_at=base if status == "delivered" else None,
    )


def nodes_for(order: models.Order, order_no: str, status: str, start: datetime) -> list[models.DeliveryNode]:
    nodes: list[models.DeliveryNode] = []
    if status not in ORDER_STATUS_FLOW:
        return nodes
    idx = ORDER_STATUS_FLOW.index(status)
    t = start
    for k, s in enumerate(ORDER_STATUS_FLOW[1 : idx + 1], 1):
        nt = STATUS_TO_NODE[s]
        t = t + timedelta(minutes=6 * k)
        nodes.append(
            models.DeliveryNode(
                order_id=order.id,
                node_type=nt,
                occurred_at=t,
                longitude=order.longitude,
                latitude=order.latitude,
                courier_name=COURIERS[k % len(COURIERS)],
                vehicle_id=VEHICLES[k % len(VEHICLES)],
                note=f"{order_no} 节点 {nt}",
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

        # 12 个订单，覆盖各状态
        rows = [
            ("pending", "张伟", "桃李园", "5-302", "川味小馆", "麻辣香锅+米饭"),
            ("pending", "李娜", "桃李园", "3-105", "兰州拉面", "牛肉拉面+煎蛋"),
            ("picked", "王强", "丁香园", "1-208", "沙县小吃", "鸡腿饭+例汤"),
            ("handover", "刘洋", "丁香园", "2-411", "麦当劳", "巨无霸套餐"),
            ("in_campus", "陈静", "梅园", "6-120", "真功夫", "香菇滑鸡饭"),
            ("arrived_site", "杨帆", "梅园", "7-303", "必胜客", "夏威夷披萨"),
            ("dorm_delivery", "赵敏", "竹园", "4-216", "华莱士", "香辣鸡腿堡"),
            ("dorm_delivery", "孙磊", "竹园", "8-508", "老北京炸酱面", "炸酱面+北冰洋"),
            ("delivered", "周杰", "桃李园", "2-110", "黄焖鸡米饭", "黄焖鸡+可乐"),
            ("delivered", "吴倩", "丁香园", "1-305", "冒菜", "素冒菜+米饭"),
            ("delivered", "郑爽", "梅园", "5-220", "石锅拌饭", "牛肉石锅拌饭"),
            ("abnormal", "冯巩", "竹园", "3-404", "麻辣烫", "麻辣烫+冰红茶"),
        ]
        orders: list[models.Order] = []
        for i, (status, name, dorm, room, vendor, food) in enumerate(rows, 1):
            o = make_order(i, status, name, dorm, room, vendor, food)
            db.add(o)
            db.flush()
            nodes = nodes_for(o, o.order_no, status, o.created_at)
            for n in nodes:
                db.add(n)
            orders.append(o)
        db.commit()

        # 异常记录
        abnormal_order = orders[-1]
        db.add(
            models.Anomaly(
                order_id=abnormal_order.id,
                anomaly_type="lost",
                reported_at=datetime.now() - timedelta(minutes=20),
                reported_by=abnormal_order.customer_name,
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

        # 调度：车次
        db.add(
            models.VehicleTrip(
                trip_no=f"TRIP{datetime.now():%m%d%H%M}-1",
                scheduled_at=datetime.now(),
                driver_name="刘师傅",
                capacity=40,
                load=6,
                route=[
                    {"point": "校门交接点", "lon": 116.3010, "lat": 39.9060},
                    {"point": "桃李园", "lon": 116.3030, "lat": 39.9070},
                    {"point": "丁香园", "lon": 116.3050, "lat": 39.9080},
                ],
                order_ids=[o.id for o in orders[:6]],
                status="departed",
            )
        )
        db.add(
            models.VehicleTrip(
                trip_no=f"TRIP{datetime.now():%m%d%H%M}-2",
                scheduled_at=datetime.now() + timedelta(minutes=30),
                driver_name="陈师傅",
                capacity=40,
                load=0,
                route=[],
                order_ids=[],
                status="scheduled",
            )
        )

        # 调度：人力分配
        for dorm, name, cnt in [("桃李园", "小马", 4), ("丁香园", "小何", 3), ("竹园", "小杨", 2)]:
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

        print("✅ 演示数据已灌入：")
        print(f"   订单 {len(orders)} 个（覆盖 待配送/配送中/已送达/异常 等状态）")
        print(f"   轨迹节点 {db.query(models.DeliveryNode).count()} 条")
        print(f"   异常 {db.query(models.Anomaly).count()} 条")
        print(f"   车次 {db.query(models.VehicleTrip).count()} 班、人力分配 {db.query(models.StaffShift).count()} 人、订阅 {db.query(models.NotificationSubscription).count()} 条")
        print("   刷新浏览器可看到仪表盘数字变化。")
    finally:
        db.close()


if __name__ == "__main__":
    main()