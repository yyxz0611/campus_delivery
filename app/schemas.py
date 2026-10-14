"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---- 登录/用户 ----
class LoginRequest(BaseModel):
    phone: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    phone: str
    email: str
    password: str
    role: str  # rider / student（管理员不外置注册）


class UserOut(BaseModel):
    id: int
    name: str
    phone: str
    email: str
    role: str
    balance: float
    dorm_building: str = ""
    dorm_room: str = ""
    token: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None


class SendCodeRequest(BaseModel):
    email: str


class ChangePasswordRequest(BaseModel):
    phone: str
    role: str
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    phone: str
    role: str
    password: str
    name: Optional[str] = None
    email: Optional[str] = None
    email_code: Optional[str] = None
    dorm_building: Optional[str] = None
    dorm_room: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    role: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str


class RechargeRequest(BaseModel):
    user_id: int
    amount: float
    description: str = ""


class AdminResetPasswordRequest(BaseModel):
    role: str
    new_password: str


# ---- 订单 ----
class OrderCreate(BaseModel):
    order_no: str
    customer_name: str
    customer_phone: str = ""
    dorm_building: str
    dorm_room: str
    vendor_name: str
    vendor_phone: str = ""
    food_items: str = ""
    source: str = "manual"  # manual 手动录入 / ocr 自动识别
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    expected_delivery_at: Optional[datetime] = None


class OrderBatchCreate(BaseModel):
    orders: list[OrderCreate]


class OrderOut(BaseModel):
    id: int
    order_no: str
    customer_name: str
    dorm_building: str
    dorm_room: str
    vendor_name: str
    food_items: str
    status: str
    source: str
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    created_at: datetime
    expected_delivery_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrderStatusUpdate(BaseModel):
    status: str
    courier_name: str = ""
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    note: str = ""
    location_only: bool = False


# ---- 轨迹 ----
class NodeOut(BaseModel):
    id: int
    node_type: str
    occurred_at: datetime
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    courier_name: str
    vehicle_id: str
    note: str

    model_config = {"from_attributes": True}


class NodeCreate(BaseModel):
    order_id: int
    node_type: str
    occurred_at: Optional[datetime] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    courier_name: str = ""
    vehicle_id: str = ""
    note: str = ""


# ---- 照片 ----
class PhotoOut(BaseModel):
    id: int
    order_id: int
    node_id: Optional[int] = None
    file_path: str
    audit_status: str
    audit_metrics: dict
    audit_result: dict
    reject_reason: str

    model_config = {"from_attributes": True}


# ---- 异常 ----
class AnomalyCreate(BaseModel):
    order_id: int
    anomaly_type: str
    reported_by: str = ""
    description: str = ""


class AnomalyHandle(BaseModel):
    action: str
    operator: str = ""
    detail: str = ""


class AnomalyOut(BaseModel):
    id: int
    order_id: int
    anomaly_type: str
    reported_at: datetime
    reported_by: str
    description: str
    status: str
    located_node_type: Optional[str] = None
    handle_log: list
    compensation_granted: bool
    compensation_amount: float
    resolution: str

    model_config = {"from_attributes": True}


# ---- 调度 ----
class DispatchPlan(BaseModel):
    dorm_building: Optional[str] = None
    trips: list = Field(default_factory=list)
    staff: list = Field(default_factory=list)


# ---- 通知 ----
class SubscriptionCreate(BaseModel):
    order_id: Optional[int] = None
    channel: str = "app_push"
    contact: str = ""


class SubscriptionOut(BaseModel):
    id: int
    order_id: Optional[int] = None
    channel: str
    contact: str
    active: bool
    subscribed_at: datetime

    model_config = {"from_attributes": True}