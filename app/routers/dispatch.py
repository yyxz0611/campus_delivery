"""统筹调度路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import dispatch_service

router = APIRouter(prefix="/api/dispatch", tags=["dispatch"])


@router.post("/plan")
def plan(db: Session = Depends(get_db)):
    plan = dispatch_service.plan_dispatch(db)
    dispatch_service.persist_plan(db, plan)
    return plan


@router.get("/plan")
def get_plan(db: Session = Depends(get_db)):
    return dispatch_service.plan_dispatch(db)


@router.get("/trips")
def trips(db: Session = Depends(get_db)):
    rows = dispatch_service.latest_trips(db)
    return [
        {
            "id": t.id,
            "trip_no": t.trip_no,
            "scheduled_at": t.scheduled_at.isoformat(),
            "driver_name": t.driver_name,
            "capacity": t.capacity,
            "load": t.load,
            "route": t.route,
            "order_ids": t.order_ids,
            "status": t.status,
        }
        for t in rows
    ]


@router.get("/staff")
def staff(db: Session = Depends(get_db)):
    rows = dispatch_service.latest_staff(db)
    return [
        {
            "id": s.id,
            "dorm_building": s.dorm_building,
            "courier_name": s.courier_name,
            "order_count": s.order_count,
            "time_window": s.time_window,
        }
        for s in rows
    ]