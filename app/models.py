"""ORM 数据模型：外卖订单、配送轨迹、照片审核、异常、车次调度、人力分配、通知订阅。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now()


class User(Base):
    """平台自然人：按手机号唯一确认「人」，通过多个角色凭据登录不同身份。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(128), default="")
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    dorm_building: Mapped[str] = mapped_column(String(64), default="")
    dorm_room: Mapped[str] = mapped_column(String(32), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    credentials: Mapped[list["UserCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserCredential(Base):
    """角色凭据：一个人可拥有多个角色，每个角色一套独立密码。"""

    __tablename__ = "user_credentials"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    role: Mapped[str] = mapped_column(String(16))  # admin / rider / student
    password_hash: Mapped[str] = mapped_column(String(128), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user: Mapped["User"] = relationship(back_populates="credentials")


class Order(Base):
    """外卖订单（用餐人视角的核心实体）。"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(64))
    customer_phone: Mapped[str] = mapped_column(String(32), default="")
    dorm_building: Mapped[str] = mapped_column(String(64))  # 宿舍楼栋
    dorm_room: Mapped[str] = mapped_column(String(32))  # 寝室号
    vendor_name: Mapped[str] = mapped_column(String(64))
    vendor_phone: Mapped[str] = mapped_column(String(32), default="")
    food_items: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    source: Mapped[str] = mapped_column(String(16), default="ocr")  # 录入来源：ocr 自动 / manual 手动
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    rider_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expected_delivery_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    nodes: Mapped[list["DeliveryNode"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="DeliveryNode.occurred_at"
    )


class DeliveryNode(Base):
    """配送轨迹节点：每一次交接/运输/到达/交付都会产生带时间戳+经纬度的日志。"""

    __tablename__ = "delivery_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)

    node_type: Mapped[str] = mapped_column(String(32))  # pickup / external_handover / internal_transport / site_arrival / dorm_delivery / completed
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    courier_name: Mapped[str] = mapped_column(String(64), default="")
    vehicle_id: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")

    order: Mapped["Order"] = relationship(back_populates="nodes")
    photos: Mapped[list["PhotoRecord"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class PhotoRecord(Base):
    """节点照片上传 + 审核结果（黑图/花图/模糊/单号/寝室号/环境）。"""

    __tablename__ = "photo_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("delivery_nodes.id"), nullable=True)

    file_path: Mapped[str] = mapped_column(String(256))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    audit_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending / passed / rejected
    audit_metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # 亮度/熵/模糊度等
    audit_result: Mapped[dict] = mapped_column(JSON, default=dict)  # 是否黑图/花图/模糊/含单号/含寝室号/环境
    reject_reason: Mapped[str] = mapped_column(Text, default="")

    node: Mapped["DeliveryNode | None"] = relationship(back_populates="photos")


class Anomaly(Base):
    """配送异常（丢失/未到寝）及应急处理闭环。"""

    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)

    anomaly_type: Mapped[str] = mapped_column(String(32))  # lost / not_delivered
    reported_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    reported_by: Mapped[str] = mapped_column(String(64), default="")
    reported_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reported_role: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending / investigating / located / compensated / resolved
    located_node_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    handle_log: Mapped[list] = mapped_column(JSON, default=list)

    compensation_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    compensation_amount: Mapped[float] = mapped_column(Float, default=0.0)
    resolution: Mapped[str] = mapped_column(Text, default="")


class VehicleTrip(Base):
    """运输车车次：批量化携带订单 + 最优路线。"""

    __tablename__ = "vehicle_trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trip_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    driver_name: Mapped[str] = mapped_column(String(64), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=40)
    load: Mapped[int] = mapped_column(Integer, default=0)

    route: Mapped[list] = mapped_column(JSON, default=list)  # [{point, lon, lat}]
    order_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="scheduled")  # scheduled / departed / arrived / finished


class StaffShift(Base):
    """各宿舍楼下人力分配。"""

    __tablename__ = "staff_shifts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dorm_building: Mapped[str] = mapped_column(String(64), index=True)
    shift_time: Mapped[str] = mapped_column(String(64), default="")
    courier_name: Mapped[str] = mapped_column(String(64))
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    time_window: Mapped[str] = mapped_column(String(64), default="")


class NotificationSubscription(Base):
    """送达通知订阅。"""

    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(32), default="app_push")  # app_push / sms / inapp
    contact: Mapped[str] = mapped_column(String(64), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Notification(Base):
    """持久化通知记录。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, default="")
    target_role: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    target_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class NotificationUserState(Base):
    """用户对通知的已读/删除状态（每人独立）。"""

    __tablename__ = "notification_user_states"
    __table_args__ = (UniqueConstraint("notification_id", "user_id", name="uq_notif_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class BalanceTransaction(Base):
    """账户余额流水：充值/补偿/退款/消费。"""

    __tablename__ = "balance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(16))  # recharge / compensation / refund / consume
    amount: Mapped[float] = mapped_column(Float)  # 正数=入账，负数=扣减
    balance_after: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)