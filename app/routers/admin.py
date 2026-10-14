"""管理员路由：人员管理（阶段3）。权限校验留待阶段4统一接入会话后补齐。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return admin_service.list_users(db)


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db)):
    detail = admin_service.get_user_detail(db, user_id)
    if detail is None:
        raise HTTPException(404, "用户不存在")
    return detail


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, payload: schemas.AdminResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        admin_service.reset_user_password(db, user_id, payload.role, payload.new_password)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/users/{user_id}/credentials/{role}")
def remove_role(user_id: int, role: str, db: Session = Depends(get_db)):
    try:
        admin_service.remove_role(db, user_id, role)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    try:
        admin_service.delete_user(db, user_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/users/{user_id}/orders")
def user_orders(user_id: int, db: Session = Depends(get_db)):
    return admin_service.user_orders(db, user_id)