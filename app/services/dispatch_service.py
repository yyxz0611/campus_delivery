"""统筹调度：运输车车次规划、校内最优路线（贪心 TSP）、宿舍楼下人力分配。

路线距离优先使用高德「步行路径规划」的真实路网距离；未配置 AMAP_KEY 时降级为球面直线距离。
"""
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from .amap_client import amap, haversine

# 校园楼栋「楼下站点」真实经纬度（lon, lat）—— 均在路网道路上，便于高德步行规划顺着路网走。
CAMPUS_BUILDINGS = {
    "致远居1栋": [103.88316, 30.786795],
    "致远居2栋": [103.884069, 30.786304],
    "致远居3栋": [103.884423, 30.786118],
    "致远居4栋": [103.885607, 30.785493],
    "致远居5栋": [103.884529, 30.786571],
    "致远居6栋": [103.885455, 30.78625],
}
# 校门（校外骑手交接点）。多门交接：调度按订单就近分配大门。
GATES = {
    "一号门": [103.888963, 30.788656],
    "西门": [103.881499, 30.787709],
    "西北门": [103.883135, 30.789934],
}

TRANSPORT_STATUSES = ["handover", "in_campus", "arrived_site", "dorm_delivery"]
VEHICLE_CAPACITY = 40
COURIER_CAPACITY = 30


def _coords(building: str) -> list[float]:
    if building in CAMPUS_BUILDINGS:
        return CAMPUS_BUILDINGS[building]
    # 未知楼栋给一个基于哈希的稳定偏移（相对一号门）
    h = sum(ord(c) for c in building) % 100
    gate = GATES["一号门"]
    return [gate[0] + h * 0.0005, gate[1] + (h % 50) * 0.0003]


_seg_cache: dict[tuple, dict] = {}


def _segment(a: tuple[float, float], b: tuple[float, float]) -> dict:
    """两楼栋间真实路径：{distance(米), polyline([[lon,lat],...])}，带缓存。"""
    key = (a, b) if a <= b else (b, a)
    if key in _seg_cache:
        return _seg_cache[key]
    seg: dict = {"distance": 0.0, "polyline": []}
    if amap.enabled:
        try:
            r = amap.walking(a, b)
            if r and r.get("distance") and r.get("polyline"):
                seg["distance"] = float(r["distance"])
                seg["polyline"] = r["polyline"]
        except Exception:
            pass
    if seg["distance"] <= 0 or not seg["polyline"]:
        seg["distance"] = haversine(a, b)
        seg["polyline"] = [[a[0], a[1]], [b[0], b[1]]]
    _seg_cache[key] = seg
    return seg


def _dist(a: list[float], b: list[float]) -> float:
    """两楼栋间真实距离（米）。"""
    return _segment((a[0], a[1]), (b[0], b[1]))["distance"]


def _pick_gate(buildings: list[str]) -> tuple[str, list[float]]:
    """校外交接点固定为西门（校外骑手在西门交接，校内运输车从西门出发）。"""
    return "西门", GATES["西门"]


def _build_route(buildings: list[str]) -> list[dict]:
    """从就近大门出发的最近邻贪心路线，全程由高德道路折线拼接，避免出现直线穿楼。

    高德步行规划的 polyline 首末点是把起终点「吸附」到最近道路后的点。
    因此楼栋/大门标注点一律取折线首末点（吸附点），而不是手填坐标，
    这样画线路径 = 折线首点 → 折线 … → 折线末点，逐段首尾相接，完全贴合路网。
    """
    gate_name, gate = _pick_gate(buildings)
    remaining = list(buildings)
    route: list[dict] = []
    current = gate
    first = True
    while remaining:
        nxt = min(remaining, key=lambda b: _dist(current, _coords(b)))
        remaining.remove(nxt)
        c = _coords(nxt)
        seg = _segment((current[0], current[1]), (c[0], c[1]))
        poly = seg["polyline"]
        if first:
            start = poly[0] if poly else [gate[0], gate[1]]
            route.append({"point": gate_name, "lon": start[0], "lat": start[1]})
            first = False
        for lon, lat in poly:
            route.append({"point": "", "lon": lon, "lat": lat})
        # 楼栋标注点用折线末点（道路吸附点），保证与前一段、后一段连续
        route.append({"point": nxt, "lon": poly[-1][0], "lat": poly[-1][1]})
        # 关键：下一段起点用「吸附点」而非手填坐标，否则每栋楼处折线会断开重连、多出直线
        current = (poly[-1][0], poly[-1][1])
    return route


def _order_summary(o: models.Order) -> dict:
    return {
        "id": o.id,
        "order_no": o.order_no,
        "customer_name": o.customer_name,
        "dorm_building": o.dorm_building,
        "dorm_room": o.dorm_room,
        "vendor_name": o.vendor_name,
        "food_items": o.food_items,
        "status": o.status,
    }


def plan_dispatch(db: Session) -> dict:
    orders = list(
        db.scalars(select(models.Order).where(models.Order.status.in_(TRANSPORT_STATUSES))).all()
    )
    order_map = {o.id: o for o in orders}

    by_building: dict[str, list[models.Order]] = {}
    for o in orders:
        by_building.setdefault(o.dorm_building, []).append(o)

    trips: list[dict] = []
    current_load = VEHICLE_CAPACITY + 1  # 强制首车
    trip_no_idx = 0
    current_buildings: list[str] = []
    current_orders: list[int] = []

    for building, b_orders in by_building.items():
        for o in b_orders:
            if current_load >= VEHICLE_CAPACITY:
                if current_orders:
                    route = _build_route(current_buildings)
                    trips.append(
                        {
                            "trip_no": f"TRIP{datetime.now().strftime('%H%M%S')}-{trip_no_idx}",
                            "buildings": [p["point"] for p in route if p["point"]],
                            "order_ids": current_orders,
                            "orders": [_order_summary(order_map[oid]) for oid in current_orders],
                            "load": len(current_orders),
                            "route": route,
                        }
                    )
                    trip_no_idx += 1
                current_load = 0
                current_buildings = []
                current_orders = []
            current_orders.append(o.id)
            current_load += 1
            if building not in current_buildings:
                current_buildings.append(building)

    if current_orders:
        route = _build_route(current_buildings)
        trips.append(
            {
                "trip_no": f"TRIP{datetime.now().strftime('%H%M%S')}-{trip_no_idx}",
                "buildings": [p["point"] for p in route if p["point"]],
                "order_ids": current_orders,
                "orders": [_order_summary(order_map[oid]) for oid in current_orders],
                "load": len(current_orders),
                "route": route,
            }
        )

    # 人力分配：每楼栋按订单数与人均承载计算所需配送员
    staff: list[dict] = []
    for building, b_orders in by_building.items():
        needed = max(1, math.ceil(len(b_orders) / COURIER_CAPACITY))
        for i in range(needed):
            staff.append(
                {
                    "dorm_building": building,
                    "courier_name": f"配送员{chr(65 + i)}{building[-1]}",
                    "order_count": min(COURIER_CAPACITY, len(b_orders) - i * COURIER_CAPACITY),
                    "time_window": "11:00-13:00",
                }
            )

    return {"trips": trips, "staff": staff, "total_orders": len(orders), "vehicle_count": len(trips)}


def persist_plan(db: Session, plan: dict) -> dict:
    """将规划结果持久化为车次与人力分配记录。"""
    tripid = 0
    for t in plan["trips"]:
        db.add(
            models.VehicleTrip(
                trip_no=t["trip_no"],
                scheduled_at=datetime.now(),
                capacity=VEHICLE_CAPACITY,
                load=t["load"],
                route=t["route"],
                order_ids=t["order_ids"],
                status="scheduled",
            )
        )
        tripid += 1

    for s in plan["staff"]:
        db.add(
            models.StaffShift(
                dorm_building=s["dorm_building"],
                shift_time=datetime.now().strftime("%Y-%m-%d"),
                courier_name=s["courier_name"],
                order_count=s["order_count"],
                time_window=s["time_window"],
            )
        )
    db.commit()
    return plan


def latest_trips(db: Session) -> list[models.VehicleTrip]:
    return list(db.scalars(select(models.VehicleTrip).order_by(models.VehicleTrip.id.desc()).limit(20)).all())


def latest_staff(db: Session) -> list[models.StaffShift]:
    return list(db.scalars(select(models.StaffShift).order_by(models.StaffShift.id.desc()).limit(50)).all())