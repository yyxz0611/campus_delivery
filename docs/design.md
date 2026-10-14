# 校园外卖配送对接平台 — 技术设计文档

> 赛题：第十一届华为ICT大赛中国创新赛 · 赛题1
> 版本：v1.0 | 日期：2026-10-12

---

## 1. 系统架构

### 1.1 三层架构总览

```
┌─────────────────────────────────────────────────────────┐
│                     前端（浏览器）                        │
│  Vue3 CDN 免构建单页 + 高德 JS API（地图底图/路网/定位）   │
│  7 个功能 Tab：概览/订单/轨迹/照片审核/异常/调度/通知      │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / JSON
┌────────────────────────▼────────────────────────────────┐
│                   后端（FastAPI 应用层）                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ 9 路由   │ │ 8 服务   │ │ 安全层   │ │ 数据层   │    │
│  │ routers  │ │ services │ │ security │ │ database │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
└───────┬────────────────┬───────────────────┬────────────┘
        │                │                   │
┌───────▼──────┐ ┌──────▼───────┐ ┌─────────▼──────────┐
│ 华为云 RDS   │ │ 华为云 DCS   │ │ 高德地图 Web 服务  │
│ MySQL 12表  │ │ Redis 通知流 │ │ 路径规划/地理编码  │
└──────────────┘ └──────────────┘ └────────────────────┘
        │
┌───────▼──────────────────────────────────────────────┐
│  华为云 OCR（通用文字识别：照片单号+寝室号校验）       │
└───────────────────────────────────────────────────────┘
```

### 1.2 华为云产品拓扑

| 华为云产品 | 用途 | 在架构中的位置 |
|---|---|---|
| CodeArts 代码智能体 | 全程开发（想法到应用闭环） | 开发阶段 |
| RDS MySQL | 12 张业务表持久化 | 数据层 |
| DCS Redis | 通知流 + 热点缓存（降级进程内） | 缓存层 |
| OCR 通用文字识别 | 照片外卖单号 + 寝室号校验 | 服务层（AI） |
| ECS | 应用部署（117.78.5.155:8000） | 计算层 |
| SWR | 容器镜像托管 | 构建层 |
| VPC + 子网 + 安全组 | 网络隔离 | 网络层 |

---

## 2. 模块设计

### 2.1 路由模块（`app/routers/`，9 个）

| 模块 | 路由前缀 | 职责 |
|---|---|---|
| `auth` | `/api/auth` | 注册/登录/角色切换，签发 HMAC token |
| `orders` | `/api/orders` | 订单 CRUD，按角色过滤（学生按寝室+姓名，骑手按 rider_user_id） |
| `tracking` | `/api/tracking` | 配送轨迹节点录入与查询（6 节点全链路） |
| `photos` | `/api/photos` | 照片上传 + AI 质量审核 + OCR 文字识别 |
| `anomalies` | `/api/anomalies` | 异常上报、定位、补偿闭环 |
| `dispatch` | `/api/dispatch` | 高德路径规划 + 贪心 TSP 车次调度 + 人力分配 |
| `notifications` | `/api/notifications` | 通知列表/已读/删除（持久化，跨设备同步） |
| `admin` | `/api/admin` | 管理员专属：用户管理、全局视图 |
| `balance` | `/api/balance` | 余额流水查询（充值/补偿/退款/消费） |

### 2.2 服务模块（`app/services/`，8 个）

| 模块 | 职责 | 关键依赖 |
|---|---|---|
| `auth_service` | 密码 PBKDF2 哈希、token 签发/验证、内置管理员初始化 | `app.security` |
| `image_audit` | 三项质量指标计算（亮度/拉普拉斯方差/颜色熵）+ OCR 调用 | PIL, numpy, `app.huawei` |
| `dispatch_service` | 高德步行路径规划 + 楼栋聚合 + 贪心 TSP + 人力分配 | `app.amap_client` |
| `anomaly_service` | 异常定位 + 超时检测 + 自动补偿入账 | `app.balance_service` |
| `amap_client` | 高德地图 Web 服务封装（路径规划/地理编码/polyline 解码） | httpx |
| `balance_service` | 余额变动 + 流水记录 + 原路退款 | SQLAlchemy |
| `notification_service` | 通知创建 + 定向推送 + 已读状态管理 | `app.redis_client` |
| `huawei` | 华为云 SDK 封装（OCR/RDS/DCS/VPC/IAM 客户端单例） | huaweicloudsdk* |

### 2.3 安全层（`app/security.py`）

- **HMAC 签名 token**：格式 `uid.role.exp.sig`，7 天 TTL，密钥从 `.env` 读取
- **PBKDF2 密码哈希**：迭代 100000 次，盐值随机
- **角色隔离**：同一自然人可多角色，但 token 绑定单一角色，请求按角色过滤数据
- **手机号脱敏**：订单对非管理员隐藏完整手机号

---

## 3. 数据库设计

### 3.1 ER 关系

```
users ──┬── user_credentials（1:N，角色凭据）
        ├── orders（1:N，rider_user_id 关联）
        ├── balance_transactions（1:N，余额流水）
        └── notification_user_states（1:N，已读状态）

orders ──┬── delivery_nodes（1:N，轨迹节点）
         ├── photo_records（1:N，照片审核）
         ├── anomalies（1:N，异常记录）
         └── notification_subscriptions（1:N，通知订阅）

delivery_nodes ─── photo_records（1:N，节点关联照片）

notifications ─── notification_user_states（1:N，用户已读状态）

vehicle_trips（独立，order_ids JSON 关联订单）
staff_shifts（独立，按楼栋分配人力）
```

### 3.2 表结构明细

#### users — 平台自然人
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| name | VARCHAR(64) | 姓名 |
| phone | VARCHAR(32) UNIQUE | 手机号（唯一确认「人」） |
| email | VARCHAR(128) | 邮箱 |
| balance | FLOAT | 虚拟余额（补偿入账） |
| dorm_building | VARCHAR(64) | 宿舍楼栋 |
| dorm_room | VARCHAR(32) | 寝室号 |
| created_at / last_login_at | DATETIME | |

#### user_credentials — 角色凭据
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| user_id | INT FK→users.id | |
| role | VARCHAR(16) | admin / rider / student |
| password_hash | VARCHAR(128) | PBKDF2 哈希 |
| **UNIQUE(user_id, role)** | | 一人一角色一密码 |

#### orders — 外卖订单
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_no | VARCHAR(64) UNIQUE | 订单号 |
| customer_name / customer_phone | VARCHAR | 用餐人 |
| dorm_building / dorm_room | VARCHAR | 送达地址 |
| vendor_name / vendor_phone | VARCHAR | 商家 |
| food_items | TEXT | 餐品 |
| status | VARCHAR(32) | pending→picked_up→...→completed |
| source | VARCHAR(16) | ocr / manual |
| longitude / latitude | FLOAT | 经纬度 |
| rider_user_id | INT FK→users.id | 骑手 |
| created_at / expected_delivery_at / delivered_at | DATETIME | |

#### delivery_nodes — 配送轨迹节点
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id | |
| node_type | VARCHAR(32) | pickup / external_handover / internal_transport / site_arrival / dorm_delivery / completed |
| occurred_at | DATETIME | 时间戳 |
| longitude / latitude | FLOAT | 经纬度 |
| courier_name / vehicle_id | VARCHAR | 配送员 / 车辆 |
| note | TEXT | 备注 |

#### photo_records — 照片审核
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id / node_id | INT FK | |
| file_path | VARCHAR(256) | 图片路径 |
| audit_status | VARCHAR(32) | pending / passed / rejected |
| audit_metrics | JSON | {brightness, laplacian_var, color_entropy} |
| audit_result | JSON | {is_dark, is_noise, is_blurry, has_order_no, has_dorm_room} |
| reject_reason | TEXT | |

#### anomalies — 配送异常
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id | |
| anomaly_type | VARCHAR(32) | lost / not_delivered |
| reported_at | DATETIME | 上报时间 |
| reported_by / reported_by_user_id / reported_role | | 上报人 |
| status | VARCHAR(32) | pending→investigating→located→compensated→resolved |
| located_node_type | VARCHAR(32) | 定位到的问题环节 |
| handle_log | JSON | 处理日志（留痕） |
| compensation_granted | BOOL | 是否已补偿 |
| compensation_amount | FLOAT | 补偿金额 |

#### vehicle_trips — 运输车次
| 字段 | 类型 | 说明 |
|---|---|---|
| id / trip_no | | 车次编号 |
| driver_name / capacity / load | | 司机 / 容量40 / 已装载 |
| route | JSON | [{point, lon, lat}] 路线 |
| order_ids | JSON | 携带订单列表 |
| status | VARCHAR(32) | scheduled / departed / arrived / finished |

#### staff_shifts — 楼下人力分配
| 字段 | 类型 | 说明 |
|---|---|---|
| dorm_building | VARCHAR(64) | 楼栋 |
| shift_time / time_window | VARCHAR | 班次 / 时间窗 |
| courier_name / order_count | | 配送员 / 单量 |

#### notifications — 通知记录
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT | 关联订单 |
| title / content | | 标题 / 内容 |
| target_role / target_user_id | | 定向推送 |
| created_at | DATETIME | |

#### notification_user_states — 用户已读状态
| 字段 | 类型 | 说明 |
|---|---|---|
| notification_id | INT FK→notifications.id | |
| user_id | INT FK→users.id | |
| is_read / is_deleted | BOOL | |
| read_at | DATETIME | |
| **UNIQUE(notification_id, user_id)** | | |

#### notification_subscriptions — 通知订阅
| 字段 | 类型 | 说明 |
|---|---|---|
| order_id / channel / contact / active | | 订单 / 渠道 / 联系方式 / 启用 |

#### balance_transactions — 余额流水
| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | INT FK→users.id | |
| order_id | INT | 关联订单 |
| type | VARCHAR(16) | recharge / compensation / refund / consume |
| amount | FLOAT | 正数=入账，负数=扣减 |
| balance_after | FLOAT | 变动后余额 |
| description | TEXT | |

---

## 4. 关键流程

### 4.1 订单全链路（6 节点轨迹）

```
商家出餐 → [pickup] 取餐
         → [external_handover] 校外交接（骑手→运输车）
         → [internal_transport] 校内运输
         → [site_arrival] 楼下站点到达
         → [dorm_delivery] 到寝交付
         → [completed] 完成

每个节点：时间戳 + 经纬度 + 配送员 + 照片（强制审核）
```

### 4.2 照片审核流程

```
上传照片
  │
  ├─→ PIL+numpy 计算三项指标
  │     ├─ 平均亮度 < 30        → 拒收（黑图）
  │     ├─ 拉普拉斯方差 < 60    → 拒收（模糊）
  │     └─ 颜色熵 > 7.0         → 拒收（花图/噪声）
  │
  ├─→ 华为云 OCR 提取文字
  │     ├─ 不含外卖单号 → 拒收
  │     └─ 不含寝室号   → 拒收
  │
  └─→ 全部通过 → audit_status = passed
```

### 4.3 异常补偿闭环

```
用餐人上报"未收到"
  │
  ├─→ 按订单号秒级查轨迹 → 推断问题环节 → located_node_type
  ├─→ 通知管理员 + 骑手核查
  │
  └─→ 扫描器检测（每分钟）
        └─ 上报超 10 分钟仍无进度？
              ├─ 是 → 自动补偿：balance_service 入账学生余额 + 原路退款 + 通知
              └─ 否 → 继续等待
```

### 4.4 统筹调度流程

```
待调度订单
  │
  ├─→ 按楼栋聚合
  ├─→ 车容量 40 装箱 → 生成车次
  ├─→ 高德步行路径规划（楼栋间真实路网距离）
  ├─→ 贪心最近邻 TSP 排序（从西门出发）
  └─→ 人力按人均 30 单分配到各楼栋

注意：高德 polyline 首末点是道路吸附点 ≠ 手填坐标，
楼栋标注必须取吸附点，否则折线断开穿楼。
```

---

## 5. 技术选型

| 层 | 技术 | 选型理由 |
|---|---|---|
| 前端 | Vue3 CDN + 高德 JS API | 免构建单页，快速迭代；真实地图底图 |
| 后端 | FastAPI + SQLAlchemy 2.0 | 异步性能 + 类型安全 ORM |
| 数据校验 | Pydantic | FastAPI 原生集成 |
| 图像处理 | PIL + numpy | 轻量轻，质量指标计算 |
| 地图服务 | 高德 Web 服务 API | 真实路网路径规划 |
| 云数据库 | 华为云 RDS MySQL | 托管 MySQL，内网访问 |
| 云缓存 | 华为云 DCS Redis | 通知流，降级进程内 |
| 云 AI | 华为云 OCR | 通用文字识别，照片校验 |
| 容器化 | Docker + systemd | 镜像可移植 + 守护进程 |
| 测试 | pytest | 8 项端到端测试 |

---

## 6. 安全设计

| 威胁 | 防护措施 |
|---|---|
| 密码泄露 | PBKDF2 哈希（100000 次迭代 + 随机盐） |
| Token 伪造 | HMAC 签名（uid.role.exp.sig），密钥从 .env 注入 |
| 越权访问 | 角色隔离：学生按寝室+姓名过滤，骑手按 rider_user_id 过滤 |
| 手机号泄露 | 订单对非管理员脱敏 |
| 一人多角色歧义 | 同一用户多角色密码必须互不相同（注册/改密时校验） |
| AK/SK 泄露 | 凭证从 .env 注入，不硬编码，.gitignore 排除 |

---

## 7. 部署架构

```
华为云 ECS（117.78.5.155）
  ├── /opt/campus_delivery/    （项目代码）
  ├── /root/venv/              （Python 3.11.6 虚拟环境）
  ├── systemd campus-delivery.service（守护进程）
  └── :8000 → 对外提供 API + 前端静态资源

华为云 RDS MySQL（内网）
  └── campus_delivery 库（12 张表）

华为云 DCS Redis（内网）
  └── 通知流 + 热点缓存
```

一键开通脚本 `scripts/provision.py` 支持：
- `probe` — 列出可用资源（VPC/Subnet/Flavor）
- `create-rds --apply` — 创建 RDS 实例
- `create-dcs --apply` — 创建 DCS 实例
- `wait RDS_xxx` — 轮询状态直到 ACTIVE

---

## 8. 可量化指标

| 指标 | 数值 |
|---|---|
| 照片审核准确率 | 100%（四类样本：黑图/花图/模糊/正常） |
| 颜色熵区分度 | 噪声 14.6 vs 正常 1.3（>10 倍） |
| 拉普拉斯方差区分度 | 清晰 1019 vs 模糊 0.4 |
| 异常补偿响应 | 上报后 10 分钟自动触发，入账 < 1 秒 |
| 单车装载 | 40 单/车 |
| 人力分配 | 人均 30 单 |
| 轨迹节点 | 6 节点全链路（时间戳 + 经纬度） |
| 端到端测试 | pytest 8 项全绿 |
| 部署状态 | ECS systemd 守护稳定运行 |