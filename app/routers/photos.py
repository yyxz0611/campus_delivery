"""照片上传与审核路由。"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..services import image_audit, notification_service

router = APIRouter(prefix="/api/photos", tags=["photos"])


class PhotoUpload(BaseModel):
    order_id: int
    node_id: int | None = None
    file_base64: str
    file_ext: str = "jpg"
    expected_order_no: str = ""
    expected_room: str = ""


@router.post("/upload")
def upload_photo(payload: PhotoUpload, db: Session = Depends(get_db)):
    order = db.get(models.Order, payload.order_id)
    if order is None:
        raise HTTPException(404, "订单不存在")

    try:
        data = base64.b64decode(payload.file_base64)
    except Exception:
        raise HTTPException(400, "base64 解码失败")

    fname = f"{payload.order_id}_{uuid.uuid4().hex[:12]}.{payload.file_ext}"
    rel_path = f"uploads/{fname}"
    abs_path = settings.upload_dir / fname
    abs_path.write_bytes(data)

    passed, result, reason = image_audit.audit_image(
        data,
        expected_order_no=payload.expected_order_no or order.order_no,
        expected_room=payload.expected_room or order.dorm_room,
    )

    photo = models.PhotoRecord(
        order_id=payload.order_id,
        node_id=payload.node_id,
        file_path=rel_path,
        audit_status="passed" if passed else "rejected",
        audit_metrics=image_audit.analyze_image(data),
        audit_result=result,
        reject_reason=reason,
        uploaded_at=datetime.now(),
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    customer = order.customer_name
    notification_service.notify(
        db,
        order.id,
        "照片审核" + ("通过" if passed else "被拒"),
        f"订单 {order.order_no} 关键节点照片审核{'通过' if passed else '被拒'}{'' if passed else '：' + reason}",
    )

    return {
        "id": photo.id,
        "order_id": photo.order_id,
        "node_id": photo.node_id,
        "file_path": photo.file_path,
        "audit_status": photo.audit_status,
        "audit_metrics": photo.audit_metrics,
        "audit_result": photo.audit_result,
        "reject_reason": photo.reject_reason,
    }


@router.get("/{photo_id}")
def get_photo(photo_id: int, db: Session = Depends(get_db)):
    photo = db.get(models.PhotoRecord, photo_id)
    if photo is None:
        raise HTTPException(404, "照片不存在")
    return {
        "id": photo.id,
        "order_id": photo.order_id,
        "node_id": photo.node_id,
        "file_path": photo.file_path,
        "audit_status": photo.audit_status,
        "audit_metrics": photo.audit_metrics,
        "audit_result": photo.audit_result,
        "reject_reason": photo.reject_reason,
    }