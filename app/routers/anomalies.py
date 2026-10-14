"""异常应急处理路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..security import parse_token
from ..services import anomaly_service

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.post("", response_model=schemas.AnomalyOut)
def report(payload: schemas.AnomalyCreate, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    try:
        current = parse_token(x_auth_token)
        uid = current[0] if current else None
        role = current[1] if current else ""
        return anomaly_service.report_anomaly(db, payload, reported_by_user_id=uid, reported_role=role)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("")
def list_anomalies(x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    return [anomaly_service.to_dict(a) for a in anomaly_service.list_anomalies(db, current=current)]


@router.get("/{anomaly_id}/contacts")
def contacts(anomaly_id: int, db: Session = Depends(get_db)):
    c = anomaly_service.get_anomaly_contacts(db, anomaly_id)
    if c is None:
        raise HTTPException(404, "异常不存在")
    return c


@router.post("/{anomaly_id}/locate")
def locate(anomaly_id: int, db: Session = Depends(get_db)):
    try:
        a = anomaly_service.locate_anomaly(db, anomaly_id)
        return anomaly_service.to_dict(a)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{anomaly_id}/handle")
def handle(anomaly_id: int, payload: schemas.AnomalyHandle, db: Session = Depends(get_db)):
    try:
        a = anomaly_service.add_handle_log(db, anomaly_id, payload.action, payload.operator, payload.detail)
        return anomaly_service.to_dict(a)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{anomaly_id}/compensate")
def compensate(anomaly_id: int, db: Session = Depends(get_db)):
    try:
        a = anomaly_service.compensate(db, anomaly_id)
        return anomaly_service.to_dict(a)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{anomaly_id}/resolve")
def resolve(anomaly_id: int, resolution: str = "", db: Session = Depends(get_db)):
    try:
        a = anomaly_service.resolve(db, anomaly_id, resolution)
        return anomaly_service.to_dict(a)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/check-timeouts")
def check_timeouts(db: Session = Depends(get_db)):
    triggered = anomaly_service.check_timeouts(db)
    return {"triggered": [anomaly_service.to_dict(a) for a in triggered]}