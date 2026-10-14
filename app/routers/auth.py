"""登录鉴权路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..security import make_token, parse_token
from ..services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.UserOut)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    try:
        user, role = auth_service.login(db, payload.phone, payload.password)
        return auth_service.to_dict(user, role, token=make_token(user.id, role))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/register", response_model=schemas.UserOut)
def register(payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    try:
        user, role = auth_service.register(db, payload.name, payload.phone, payload.email, payload.password, payload.role)
        return auth_service.to_dict(user, role, token=make_token(user.id, role))
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.post("/send-code")
def send_code(payload: schemas.SendCodeRequest):
    try:
        auth_service.send_code(payload.email)
        return {"sent": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"邮件发送失败：{e}")


@router.post("/change-password")
def change_password(payload: schemas.ChangePasswordRequest, db: Session = Depends(get_db)):
    try:
        auth_service.change_password(db, payload.phone, payload.role, payload.old_password, payload.new_password)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/update-profile", response_model=schemas.UserOut)
def update_profile(payload: schemas.UpdateProfileRequest, db: Session = Depends(get_db)):
    try:
        user = auth_service.update_profile(
            db, payload.phone, payload.role, payload.password, payload.name, payload.email, payload.email_code, payload.dorm_building, payload.dorm_room
        )
        return auth_service.to_dict(user, payload.role, token=make_token(user.id, payload.role))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/reset-password")
def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        auth_service.reset_password(db, payload.email, payload.code, payload.role, payload.new_password)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.delete("/account")
def delete_account(payload: schemas.DeleteAccountRequest, x_auth_token: str | None = Header(None), db: Session = Depends(get_db)):
    current = parse_token(x_auth_token)
    if not current:
        raise HTTPException(401, "未登录")
    try:
        auth_service.delete_account(db, current[0], payload.password)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))