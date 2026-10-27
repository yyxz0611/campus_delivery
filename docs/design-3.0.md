# 校园外卖配送对接平台 3.0 — 技术设计文档

> 赛题：第十一届华为 ICT 大赛中国创新赛 · 赛题 1
> 版本：v3.0 | 日期：2026-10-26 | 形态：FastAPI + LangGraph 多 Agent + Vue3 单页
> 前序文档：`docs/design.md`（v1.0，2.0 基线设计）——本文档为 3.0 的**完整重写版**，2.0 文档保留作历史版本对照

---

## 0. 文档说明

### 0.1 版本演进

| 版本 | 核心形态 | 状态 |
|---|---|---|
| 2.0 | FastAPI + 规则驱动服务层（12 张表 / 9 路由 / 8 服务，按 `docs/design.md` 口径） | 已结项，已提交 GitHub（`7cc1b22`） |
| **3.0** | 在 2.0 之上叠加 **LangGraph Supervisor 多 Agent 层**，LLM 负责意图理解与编排，确定性算法仍由原服务层承担 | 本文档描述的版本 |

### 0.2 本文档的写作约束

- 所有模块数、表数、接口数、测试数均**取自代码实际统计**，不含规划项；
- 3.0 已实现与未实现的部分在第 10 章「已知边界」集中列出，不做美化；
- 涉及阈值、容量、路由规则的具体数值，与 `app/constants.py`、`app/config.py`、各 `services/*.py` 保持一致。

### 0.3 代码规模实测

| 项 | 数值 | 统计方式 |
|---|---|---|
| 后端 Python 文件 | 45 个 | `app/` 下全部 `.py` |
| 后端代码行数 | 4073 行 | 同上 |
| 测试文件 / 代码行 | 4 个 / 641 行 | `tests/` |
| 自动化测试用例 | **56 项**（可收集） | `pytest --collect-only` |
| 前端资源 | `index.html` 37KB / `app.js` 35KB / `style.css` 16KB / `vue.global.prod.js` 147KB | `frontend/` |

测试用例分布：

| 测试文件 | 用例数 | 覆盖对象 | 受限环境实测 |
|---|---|---|---|
| `tests/test_agents_graph.py` | 35 | Supervisor 路由三级降级、图结构、子 Agent 异常兜底 | 全部通过 |
| `tests/test_assistant_sessions.py` | 13 | 会话按角色隔离、通知工具权限矩阵 | 全部通过 |
| `tests/test_api.py` | 8 | 订单全链路、照片审核、异常闭环、调度、元信息 | **受限环境无法运行**（见下） |

> **测试运行环境说明**：56 项中，`agents` 与 `sessions` 共 48 项直接调用函数与 LangGraph 图，可在任意环境运行，本次实测全绿。
> `test_api.py` 的 8 项依赖 `starlette.TestClient`，其内部需启动 anyio event loop（涉及本地 socket），在**禁用本地 socket 的受限运行环境**下会被系统拦截并报 `OSError: [WinError 10051]`，属环境限制而非代码缺陷；在允许本地 socket 的正常开发环境下该 8 项通过（2.0 阶段已验证 api 8 项全绿）。

---

## 1. 系统架构

### 1.1 四层架构总览（3.0）

```
┌──────────────────────────────────────────────────────────────┐
│                      前端（浏览器）                            │
│   Vue3 CDN 免构建单页（无 node/npm 构建链）                    │
│   13 个 Tab 定义（10 个功能页 + 3 个角色视图），按登录角色过滤   │
│   概览/人员管理/订单管理/配送轨迹/照片审核/异常应急/            │
│   统筹调度/通知中心/AI 助手/个人中心 + 管理员/骑手/学生视图      │
└───────────────────────────┬──────────────────────────────────┘
                            │ HTTP / JSON
┌───────────────────────────▼──────────────────────────────────┐
│                  后端应用层（FastAPI，10 个路由模块）           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐  │
│  │ 业务路由   │ │  AI 助手   │ │  安全层    │ │  数据层   │  │
│  │ orders     │ │ /api/      │ │ HMAC token │ │ SQLAlchemy│  │
│  │ tracking   │ │ assistant  │ │ PBKDF2     │ │ 2.1 同步  │  │
│  │ photos     │ │ ★ 3.0 新增 │ └────────────┘ └───────────┘  │
│  │ anomalies  │ └─────┬──────┘                                  │
│  │ dispatch   │       │                                         │
│  │ notifications│  ┌──▼────────────────────────────────────┐   │
│  │ admin      │  │  ★ 智能体层（LangGraph，3.0 新增）      │   │
│  │ balance    │  │  supervisor ──► anomaly_agent ──► finalize│  │
│  │ auth       │  │   (Router)      (ReAct + 4 个工具)      │   │
│  └────────────┘  │   └── contextvars 注入 db session/登录身份│  │
│                   └──────┬──────────────────────────────────┘   │
└──────────────────────────┼───────────────────────────────────────┘
                           │
      ┌────────────────────┼────────────────────┬───────────────┐
      │                    │                    │               │
┌─────▼────────┐  ┌────────▼─────────┐  ┌───────▼───────┐ ┌─────▼─────┐
│ 华为云 RDS   │  │ 华为云 DCS Redis │  │  MiniMax API  │ │ 高德 Web   │
│ MySQL        │  │ 通知流 + 热点缓存 │  │ (OpenAI 兼容)  │ │ 服务 API   │
│ 12 张业务表  │  │ ↓ 降级进程内实现  │  │ minimax-m3    │ │ 步行路径   │
└──────────────┘  └──────────────────┘  └───────────────┘ └───────────┘
      │
┌─────▼──────────────────────────────────────────────────────────┐
│  华为云 OCR（通用文字识别）—— 照片中单号/寝室号校验，可选挂载   │
└────────────────────────────────────────────────────────────────┘
```

### 1.2 华为云产品拓扑

| 华为云产品 | 用途 | 在 3.0 架构中的位置 |
|---|---|---|
| CodeArts 代码智能体 | 全程开发（需求→编码→自检→部署） | 开发阶段 |
| RDS MySQL | 12 张业务表持久化 | 数据层 |
| DCS Redis | 通知流 + 热点缓存（未配置降级进程内） | 缓存层 |
| OCR 通用文字识别 | 照片中外卖单号 + 寝室号校验（可选启用） | 服务层（AI） |
| ECS | 应用部署（`117.78.5.155:8000`） | 计算层 |
| SWR | 容器镜像托管 | 构建层 |
| VPC + 子网 + 安全组 | 网络隔离 | 网络层 |

### 1.3 3.0 相对 2.0 的架构变更

| 维度 | 2.0 | 3.0 | 变更性质 |
|---|---|---|---|
| 请求入口 | 9 个业务路由 | 10 个路由，新增 `/api/assistant/chat` | 新增 |
| 智能编排 | 无（前端点按钮 → 后端规则执行） | LangGraph Supervisor 按自然语言意图路由 | **新增** |
| 业务能力实现位置 | 全部在 service 层 | **仍在 service 层**，LLM 只做理解与编排 | **不变**（关键原则） |
| 工具调用安全 | HTTP 层鉴权 | 复用同一 HMAC token + 同一订单权限模型 | 复用 |
| 数据表 | 12 张 | 12 张（**未新增表**） | 不变 |
| 部署依赖 | RDS/DCS/高德 | 同上 + 外部 LLM 端点（MiniMax） | 新增一项外部依赖 |

**架构原则（贯穿全文）**：LLM 只承担「意图理解 + 编排 + 自然语言交互」三件事；**所有确定性算法（高德路径规划、贪心 TSP、车次装箱、照片审核阈值、异常补偿、超时判定、余额变更）仍由 2.0 的 service 层执行**，不被 LLM 化、不由模型输出决定业务结果。

---

## 2. 模块设计

### 2.1 路由模块（`app/routers/`，10 个）

| 模块 | 路由前缀 | 职责 | 3.0 变化 |
|---|---|---|---|
| `auth` | `/api/auth` | 注册/登录/角色切换/改密/找回密码，签发 HMAC token | — |
| `orders` | `/api/orders` | 订单 CRUD、批量导入、状态流转（自动生成轨迹节点），按角色过滤 | — |
| `tracking` | `/api/tracking` | 轨迹节点录入与查询（6 节点全链路） | — |
| `photos` | `/api/photos` | 照片上传 + PIL/numpy 质量审核 + 可选 OCR 文字识别 | — |
| `anomalies` | `/api/anomalies` | 异常上报 → 定位 → 核查 → 补偿 → 闭环，含超时扫描 | — |
| `dispatch` | `/api/dispatch` | 车次规划 / 路线 / 人力分配 | — |
| `notifications` | `/api/notifications` | 通知历史、已读、删除（DB 持久化，跨设备同步） | — |
| `admin` | `/api/admin` | 管理员专属：人员管理、重置密码、解绑角色、关联订单 | — |
| `balance` | `/api/balance` | 虚拟余额流水查询 / 充值 | — |
| **`assistant`** | **`/api/assistant`** | **自然语言聊天入口，内部走 LangGraph Supervisor** | **3.0 新增** |

`/api/assistant` 对外只有 1 个接口：

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| POST | `/api/assistant/chat` | `{message: str, thread_id: str}` | `{reply: str, thread_id: str}` |

异常策略：任何内部错误都**降级为一条友好回复（HTTP 200）**，不把 500 堆栈抛给前端，真实原因写服务端日志。

### 2.2 服务模块（`app/services/`，12 个）

| 模块 | 职责 | 关键依赖 |
|---|---|---|
| `auth_service` | 密码 PBKDF2 哈希、token 签发/校验、一人多角色密码唯一性校验、内置管理员初始化 | `app.security` |
| `order_service` | 订单创建/批量导入/查询、状态机单调前进（只前进不倒退）、状态流转自动生成轨迹节点 | `risk_service` |
| `tracking_service` | 轨迹节点写入与查询、订单完整日志（轨迹 + 异常）拼装 | SQLAlchemy |
| `image_audit` | 四项图像指标计算 + 审核判定 + 华为云 OCR 调用与降级 | PIL, numpy, `app.huawei` |
| `anomaly_service` | 异常上报/定位/核查留痕/超时自动补偿/闭环解决/关联联系人 | `balance_service`, `notification_service` |
| `dispatch_service` | 楼栋聚合、车次装箱、贪心 TSP 路线、楼下人力分配 | `amap_client` |
| `amap_client` | 高德地理编码 + 步行路径规划 + polyline 解码 + haversine 降级 | requests |
| `balance_service` | 虚拟余额充值/补偿/退款/消费与流水 | SQLAlchemy |
| `notification_service` | 通知落库 + Redis 推送 + 定向可见性 + 已读/删除状态 | `app.redis_client` |
| `risk_service` | 规则化配送风险打分（停留时长 / 超时 / 异常信号），输出可解释原因 | SQLAlchemy |
| `email_service` | SMTP 发送验证码（QQ 邮箱 465 SSL） | smtplib |
| `admin_service` | 人员列表/详情/重置密码/解绑角色/关联订单轨迹 | SQLAlchemy |

### 2.3 智能体层（`app/agents/`，3.0 新增，11 个 Python 文件）

其中 8 个为实现文件，3 个为包初始化文件（`__init__.py`）。

| 文件 | 职责 | 关键设计 |
|---|---|---|
| `graph.py` | LangGraph 图定义：supervisor → anomaly_agent → supervisor → finalize | 三级降级路由；懒加载单例；防来回打转 |
| `agents/anomaly_agent.py` | 异常应急子 Agent（ReAct 循环） | 基于 `create_react_agent`；外层包异常兜底 |
| `tools/anomaly_tools.py` | 3 个工具：`query_order_log` / `report_anomaly` / `list_my_anomalies` | 工具内部复用 2.0 service 与权限模型 |
| `tools/notification_tools.py` | 1 个工具：`send_notification` | 权限矩阵由代码强制，非由 prompt 约束 |
| `llm.py` | 模型工厂：`get_llm(temperature=0.1)` | MiniMax 经 OpenAI 兼容端点接入 LangChain |
| `context.py` | `contextvars` 传递 db session 与当前登录身份 | 工具在 LLM 调用链中仍能拿到身份 |
| `prompts.py` | Supervisor 与子 Agent 的 system prompt 集中管理 | prompt 只约束表述与顺序，不承担安全 |
| `text_utils.py` | `strip_think` / `loads_first_json` | 清洗推理模型 `<think>` 块与噪声文本中的 JSON |

**状态定义**（`AgentState`）：

```python
class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]   # 消息累积，add_messages 归约
    next: str                                  # 下一跳：anomaly_agent / FINISH
    reply: str                                 # 给用户的一句话回复
    routed: bool                               # 本轮是否已路由（防打转）
```

**图结构**：

```
START → supervisor ─┬─(next=anomaly_agent)→ anomaly_agent → supervisor
                    └─(next=FINISH)────────→ finalize ───────→ END
```

- `supervisor` 在 `routed=True` 或本轮已有 AI 回复时直接返回 `FINISH`，避免 supervisor ↔ agent 互相打转；
- 路由状态在**每轮请求入口重置**（`routed=False`），保证多轮对话中每轮都能重新路由；
- `finalize` 负责兜底文案：模型没给回复时输出默认引导语。

**模型配置**：

| 项 | 值 | 来源 |
|---|---|---|
| 模型 | `minimax-m3` | `MINIMAX_MODEL` |
| 端点 | `https://api.minimaxi.com/v1`（OpenAI 兼容） | `MINIMAX_BASE_URL` |
| 温度 | 0.1 | `get_llm()` 默认值 |
| 最大 token | 8192 | `MINIMAX_MAX_TOKENS`（推理链会占用预算，过小会截断回答） |
| 降级开关 | `minimax_enabled = bool(MINIMAX_API_KEY)` | 未配置时 `/api/assistant/chat` 返回 503 |

### 2.4 安全层（`app/security.py`）

- **HMAC 签名 token**：格式 `uid.role.exp.sig`，TTL 7 天，密钥 `AUTH_SECRET` 从 `.env` 注入；
- 校验使用 `hmac.compare_digest`（常量时间比较，防时序侧信道）；
- **PBKDF2 密码哈希**：迭代 100000 次 + 随机盐；
- **角色隔离**：token 绑定单一角色，同一自然人可用多个角色登录，但每个角色一套独立密码（注册/改密/重置时校验唯一性）。

### 2.5 前端（`frontend/`）

| 文件 | 说明 |
|---|---|
| `index.html` | Vue3 模板 + 13 个 Tab 定义 |
| `app.js` | 应用逻辑：`visibleTabs` 按角色过滤 Tab；学生视图的「订单管理」自动改名为「我的订单」 |
| `style.css` | 样式 |
| `vue.global.prod.js` | 本地托管的 Vue3 生产包（无外网 CDN 依赖） |

Tab 集合共 13 项：10 个功能页 `概览 / 人员管理 / 订单管理 / 配送轨迹 / 照片审核 / 异常应急 / 统筹调度 / 通知中心 / AI 助手 / 个人中心`，加 3 个角色视图入口 `管理员 / 骑手 / 学生`。`visibleTabs` 按当前登录角色过滤可见集合；学生视图下「订单管理」自动改名为「我的订单」。

---

## 3. 数据库设计

### 3.1 ER 关系（3.0 未变更）

```
users ──┬── user_credentials（1:N，角色凭据，唯一 user_id+role）
        ├── orders（1:N，rider_user_id 关联）
        ├── balance_transactions（1:N，余额流水）
        └── notification_user_states（1:N，已读/删除状态）

orders ──┬── delivery_nodes（1:N，轨迹节点）
         ├── photo_records（1:N，照片审核）
         ├── anomalies（1:N，异常记录）
         └── notification_subscriptions（1:N，通知订阅）

delivery_nodes ─── photo_records（1:N，节点关联照片）

notifications ─── notification_user_states（1:N，用户已读状态）

vehicle_trips（独立，order_ids JSON 关联订单）
staff_shifts（独立，按楼栋分配人力）
```

### 3.2 表结构明细（12 张）

#### users — 平台自然人
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| name | VARCHAR(64) | 姓名 |
| phone | VARCHAR(32) UNIQUE INDEX | 手机号，唯一确认「人」 |
| email | VARCHAR(128) | 邮箱 |
| balance | FLOAT | 虚拟余额（补偿入账） |
| dorm_building / dorm_room | VARCHAR | 宿舍楼栋 / 寝室号（学生订单过滤依据） |
| created_at / last_login_at | DATETIME | |

#### user_credentials — 角色凭据
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| user_id | INT FK→users.id INDEX | |
| role | VARCHAR(16) | admin / rider / student |
| password_hash | VARCHAR(128) | PBKDF2 哈希 |
| **UNIQUE(user_id, role)** | | 一人一角色一密码 |

#### orders — 外卖订单
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_no | VARCHAR(64) UNIQUE INDEX | 订单号 |
| customer_name / customer_phone | VARCHAR | 用餐人 |
| dorm_building / dorm_room | VARCHAR | 送达地址（学生权限过滤依据） |
| vendor_name / vendor_phone | VARCHAR | 商家 |
| food_items | TEXT | 餐品 |
| status | VARCHAR(32) INDEX | `pending → picked → handover → in_campus → arrived_site → dorm_delivery → delivered`（另有 `cancelled` / `abnormal`） |
| source | VARCHAR(16) | `ocr` 自动 / `manual` 手动 |
| longitude / latitude | FLOAT NULL | 实时位置 |
| rider_user_id | INT FK→users.id NULL INDEX | 承接骑手 |
| created_at / expected_delivery_at / delivered_at | DATETIME | |

#### delivery_nodes — 配送轨迹节点
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id INDEX | |
| node_type | VARCHAR(32) | `pickup / external_handover / internal_transport / site_arrival / dorm_delivery / completed` |
| occurred_at | DATETIME | 时间戳 |
| longitude / latitude | FLOAT NULL | 经纬度 |
| courier_name / vehicle_id | VARCHAR | 配送员 / 车辆 |
| note | TEXT | 备注 |

#### photo_records — 照片审核
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id INDEX | |
| node_id | INT FK→delivery_nodes.id NULL | |
| file_path | VARCHAR(256) | 相对路径 `uploads/…` |
| audit_status | VARCHAR(32) | pending / passed / rejected |
| audit_metrics | JSON | `{brightness, edge_variance, entropy, color_entropy}` |
| audit_result | JSON | `{is_black, is_blurry, is_flower_noise, has_order_no, has_room, has_context, ocr_mode}` |
| reject_reason | TEXT | 拒收原因 |

#### anomalies — 配送异常
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id INDEX | |
| anomaly_type | VARCHAR(32) | `lost` 外卖丢失 / `not_delivered` 未配送到寝 |
| reported_at | DATETIME | 上报时间 |
| reported_by / reported_by_user_id / reported_role | | 上报人（3.0 新增 `reported_role` 用于 Agent 路径） |
| status | VARCHAR(32) | `pending → investigating → located → compensated → resolved` |
| located_node_type | VARCHAR(32) NULL | 自动定位到的异常环节 |
| handle_log | JSON | 处理留痕（动作/操作人/描述/时间戳） |
| compensation_granted / compensation_amount | BOOL / FLOAT | 是否补偿 / 金额 |
| resolution | TEXT | 闭环结论 |

#### vehicle_trips — 运输车次
| 字段 | 类型 | 说明 |
|---|---|---|
| id / trip_no | INT PK / VARCHAR(64) UNIQUE | 车次编号 |
| scheduled_at / driver_name | DATETIME / VARCHAR | 计划时间 / 司机 |
| capacity / load | INT | 容量 40 / 已装载数 |
| route | JSON | `[{point, lon, lat}]` 路线折线 |
| order_ids | JSON | 携带订单 id 列表 |
| status | VARCHAR(32) | scheduled / departed / arrived / finished |

#### staff_shifts — 楼下人力分配
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| dorm_building | VARCHAR(64) INDEX | 楼栋 |
| shift_time / time_window | VARCHAR | 班次日期 / 时间窗 |
| courier_name | VARCHAR | 配送员 |
| order_count | INT | 承接单量（人均上限 30） |

#### notification_subscriptions — 通知订阅
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id NULL INDEX | |
| channel | VARCHAR(32) | app_push / sms / inapp |
| contact | VARCHAR(64) | 联系方式 |
| active | BOOL | 是否启用 |

#### notifications — 通知记录
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| order_id | INT FK→orders.id NULL INDEX | |
| title / content | VARCHAR(128) / TEXT | |
| target_role | VARCHAR(16) NULL INDEX | 按角色广播 |
| target_user_id | INT NULL INDEX | 定向到具体用户 |
| created_at | DATETIME INDEX | |

#### notification_user_states — 用户通知状态
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| notification_id | INT FK→notifications.id INDEX | |
| user_id | INT FK→users.id INDEX | |
| is_read / is_deleted | BOOL | 每人独立 |
| read_at | DATETIME NULL | |
| **UNIQUE(notification_id, user_id)** | | |

#### balance_transactions — 余额流水
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INT PK | |
| user_id | INT FK→users.id INDEX | |
| order_id | INT FK→orders.id NULL INDEX | |
| type | VARCHAR(16) | recharge / compensation / refund / consume |
| amount | FLOAT | 正数=入账，负数=扣减 |
| balance_after | FLOAT | 变动后余额 |
| description / created_at | TEXT / DATETIME INDEX | |

### 3.3 3.0 与数据层的关系（重要）

3.0 **没有新增任何数据表**，原因是：

1. AI 会话的短期记忆由 LangGraph checkpoint 承担（当前 `MemorySaver`，进程内）；
2. Agent 的每一次工具调用最终都落到 2.0 的既有表上——异常写 `anomalies`，通知写 `notifications` + `notification_user_states`，查询读 `orders` / `delivery_nodes`；
3. 因此**3.0 不产生新的数据孤岛**，审计与回溯仍沿用同一套表。

生产环境若要持久化多轮对话，只需把 `build_graph()` 中的 `checkpointer=MemorySaver()` 换成 `langgraph.checkpoint.redis.RedisSaver`（基于 `settings.redis_url`），**无需改表**。

---

## 4. 关键流程

### 4.1 AI 助手请求全链路（3.0 核心）

```
前端「AI 助手」Tab 发送 message
   │
   ▼
POST /api/assistant/chat   {message, thread_id}
   │
   ├─ ① 鉴权：parse_token(X-Auth-Token)
   │      失败 → HTTP 401「请先登录后再使用 AI 助手」
   │
   ├─ ② 可用性：settings.minimax_enabled
   │      为假 → HTTP 503「AI 助手未配置」
   │
   ├─ ③ 会话隔离：resolve_thread_id(current, requested)
   │      前缀 = "{user_id}_{role}"
   │      请求带后缀且前缀匹配 → 采用；否则回落默认会话
   │
   ├─ ④ 上下文注入：set_context(db, current)  ← contextvars
   │      把 db session 与登录身份放进同步调用链
   │
   ├─ ⑤ 图执行：graph.invoke({messages:[user], routed:False},
   │                        config={configurable:{thread_id}})
   │      supervisor → anomaly_agent → supervisor → finalize
   │
   ├─ ⑥ 回复提取：_extract_reply(messages)
   │      取最后一条有内容 AI 消息，剥离 <think> 块
   │
   └─ ⑦ 返回 {reply, thread_id}
          任何异常 → 兜底回复（HTTP 200），异常写日志
          finally: reset_context(tokens)
```

### 4.2 Supervisor 三级降级路由

模型表现不可控，因此路由设计为三级降级，**任何一级失败都能得到回复，绝不抛错**：

```
① function calling（with_structured_output(Router, method="function_calling")）
      └─ 解析失败或未返回 tool_calls
            │
            ▼
② 模型输出 JSON 文本
      └─ 清洗 <think> → 去 ``` 围栏 → loads_first_json 提取首个合法 JSON
            └─ 仍失败
                  │
                  ▼
③ 关键词规则兜底
      命中异常/通知类关键词 → anomaly_agent
      未命中              → FINISH（输出默认引导语）
```

**路由决策 schema**（Pydantic `Router`）：

| 字段 | 类型 | 约束 |
|---|---|---|
| `next` | `Literal["anomaly_agent", "FINISH"]` | 只允许两个取值 |
| `reply` | `str` | 给用户看的一句话中文回复 |

**关键词兜底表**（`ANOMALY_KEYWORDS`，共 30 个词，分两类）：

- 异常类：`丢失 / 丢单 / 丢了 / 丢件 / 不见 / 没收到 / 未收到 / 没有收到 / 没送到 / 未送达 / 没送达 / 未送到 / 没送 / 未送 / 送错 / 送错楼 / 送错楼栋 / 异常 / 投诉 / 餐品 / 洒了 / 餐洒 / 凉了 / 漏餐 / 错餐 / 缺餐 / 坏掉`
- 通知类：`通知 / 发消息 / 发个消息 / 发信息 / 联系管理员 / 联系骑手 / 联系学生 / 告诉管理员 / 转告 / 催一下 / 催单 / 催个单 / 发个通知 / 留言`

**防打转机制**：supervisor 入口检查 `state.routed` 或「本轮已有 AI 回复」→ 直接 `FINISH`。多轮对话中每轮请求入口把 `routed` 重置为 `False`，保证第二轮能重新路由。

### 4.3 异常应急 Agent 的 ReAct 流程

```
用户：「订单 12345 到现在还没送到寝室，帮我上报一下」
   │
   ▼
anomaly_agent（ReAct 循环，create_react_agent）
   │
   ├─ 思考 → 需要订单真实状态
   │    └─ tool: query_order_log(order_no="12345")
   │            ├─ 查不到订单      → 返回「未找到订单…请核对订单号」
   │            ├─ 无权访问        → 返回「您无权查询该订单…」
   │            └─ 有权            → 返回 JSON：订单状态 + 6 类轨迹节点 + 既有异常记录
   │
   ├─ 思考 → 确认存在且未送达
   │    └─ tool: report_anomaly(order_no, anomaly_type="not_delivered", description)
   │            └─ 复用 anomaly_service.report_anomaly
   │                 ├─ 落库 anomalies（status=pending，handle_log 留痕）
   │                 ├─ 订单状态置 abnormal
   │                 └─ 通知管理员
   │
   └─ 回复：「已上报，异常已登记，后续会有负责人跟进」
```

工具调用约束（写进 `ANOMALY_AGENT_PROMPT`）：

1. 给出结论或上报前**必须先调 `query_order_log`**，禁止凭空判断；
2. 严禁编造订单号、金额、轨迹节点；
3. 补偿金额由平台规则决定，**Agent 不得擅自承诺具体数额**；
4. 订单不存在或无权访问时如实告知，不假装成功。

### 4.4 工具调用的权限校验（安全关键）

工具函数不自行判断权限，而是**复用 2.0 的订单权限模型**（`app/agents/tools/anomaly_tools.py` 与 `notification_tools.py` 内各有一份同构实现）：

| 当前身份 | 可访问订单的条件 |
|---|---|
| 管理员 admin | 全部订单 |
| 骑手 rider | `order.rider_user_id == 当前 user_id` |
| 学生 student | `user.dorm_building == order.dorm_building` **且** `user.dorm_room == order.dorm_room` **且** `user.name == order.customer_name` |

身份来自 `contextvars`（`get_current_user()`），即 FastAPI 注入的同一个 token 解析结果——**Agent 不存在提权路径**。

### 4.5 通知工具的权限矩阵

`send_notification(target, title, content, order_no="")` 的目标支持：

- `admin` / `rider` / `student` —— 按角色广播给该角色所有人；
- `user:<手机号>` —— 定向到指定用户。

| 调用者 | 可用目标 | 校验 |
|---|---|---|
| 管理员 | 任意角色 / 任意指定用户 | 指定手机号必须存在，否则返回「未找到手机号…」 |
| 学生 / 骑手 | 仅 `admin` | 指定用户或非 admin 角色一律拒绝 |

填写 `order_no` 时额外校验订单访问权，无权则**不发送**并如实返回。

### 4.6 保留的 2.0 核心流程

3.0 未改动以下流程的算法与实现，仅在自然语言入口下被 Agent 调用：

**① 订单全链路（6 节点轨迹）**

```
商家出餐 → [pickup] 取餐
         → [external_handover] 校外交接（骑手 → 运输车）
         → [internal_transport] 校内运输
         → [site_arrival] 楼下站点到达
         → [dorm_delivery] 到寝交付
         → [completed] 配送完成
每个节点：时间戳 + 经纬度 + 配送员；状态流转自动生成节点，状态只前进不倒退
```

**② 照片审核流程**

```
上传照片 → PIL + numpy 计算四项指标
    ├─ 平均亮度 < 30      → 拒收（黑图）
    ├─ 拉普拉斯方差 < 60  → 拒收（模糊）
    ├─ 颜色熵 > 7.0       → 拒收（花图/噪声）
    ├─（可选）华为云 OCR：不含外卖单号 → 拒收；不含寝室号 → 拒收
    └─ 全部通过 → audit_status = passed（同时触发通知）
OCR 调用异常 → 自动回退为纯质量审核，不阻断主流程
```

**③ 异常补偿闭环**

```
上报「未收到」
  ├─→ 按订单号定位异常环节 → located_node_type
  ├─→ 通知管理员 + 骑手核查
  └─→ 超时扫描（阈值 600 秒）
        ├─ 超时且未补偿 → 自动补偿：入账学生虚拟余额（默认 5.0 元）+ 退款 + 通知
        └─ 未超时 → 继续等待
```

**④ 统筹调度流程**

```
待调度订单（状态 ∈ handover/in_campus/arrived_site/dorm_delivery）
  ├─→ 按楼栋聚合
  ├─→ 车容量 40 装箱 → 生成车次（车次号 TRIP<时分秒>-<序号>）
  ├─→ 高德步行路径规划求楼栋间真实路网距离
  ├─→ 最近邻贪心 TSP 排序（校外交接点固定西门）
  └─→ 人力按人均 30 单分配到各楼栋
```

> 路网贴合要点：高德 `polyline` 的首末点是**道路吸附点**，不是手填坐标。楼栋标注点一律取折线末点、下一段起点取上一段末点，折线才能首尾相接，否则会出现穿楼直线。

---

## 5. 技术选型

| 层 | 技术 | 选型理由 |
|---|---|---|
| 前端 | Vue3（本地托管 CDN 包） | 免构建单页；无 node/npm 环境仍可迭代 |
| 后端框架 | FastAPI 0.116.1 | 类型注解 + 自动 OpenAPI 文档 |
| ORM | SQLAlchemy 2.1.1（同步） | 同步栈避免额外 async 驱动；2.0 风格统一 |
| 数据校验 | Pydantic 2.11.7 | 与 FastAPI 原生集成；Agent 路由决策同样用 Pydantic schema 约束 |
| Agent 编排 | LangGraph 1.2.16 | 状态图 + checkpoint 天然适配「多轮 + 工具调用 + 会话隔离」 |
| LLM 接入 | langchain-openai 1.7.2 → MiniMax（OpenAI 兼容端点） | 无需专用 SDK，模型可换 |
| Agent 记忆 | langgraph-checkpoint 4.3.0（当前 `MemorySaver`） | 生产可换 `RedisSaver` 接 DCS |
| 图像处理 | Pillow 11.3.0 + NumPy 2.3.2 | 质量指标本地实时计算 |
| 地图服务 | 高德 Web 服务 API | 真实路网路径规划 |
| 缓存/消息 | 华为云 DCS Redis 6.2.0（降级进程内） | 通知流实时推送 |
| 云数据库 | 华为云 RDS MySQL（pymysql / psycopg2 二选一） | 托管、内网访问 |
| 云 AI | 华为云 OCR | 通用文字识别校验单号/寝室号 |
| 容器化 | Docker（python:3.13-slim）+ systemd | 镜像可移植 + 守护进程 |
| 测试 | pytest | 56 项用例 |

**为什么用 LangGraph 而不是裸 LangChain AgentExecutor**：需要「主调度 → 子 Agent → 回主调度 → 收尾」的可控多跳结构、每轮重置路由状态、以及按 `thread_id` 隔离的多轮记忆，这三点用状态图实现比 AgentExecutor 直接。

---

## 6. 安全设计

### 6.1 沿用 2.0 的防护

| 威胁 | 防护措施 |
|---|---|
| 密码泄露 | PBKDF2（100000 次迭代 + 随机盐） |
| Token 伪造 | HMAC-SHA256 签名（`uid.role.exp.sig`），`compare_digest` 常量时间比较，7 天 TTL |
| 越权访问 | 角色隔离：学生按寝室+姓名过滤，骑手按 `rider_user_id` 过滤 |
| 手机号泄露 | 订单对非管理员脱敏 |
| 一人多角色歧义 | 同一用户多角色密码必须互不相同（注册/改密/重置时校验） |
| AK/SK 泄露 | 凭证仅从 `.env` 注入，不硬编码，`.gitignore` 排除 |

### 6.2 3.0 新增的 LLM 侧防护

| 威胁 | 防护措施 |
|---|---|
| **提示注入导致越权取数** | 工具执行前一律走 `_can_access_order` 判定，无权即拒绝；**权限判断在代码里，不在 prompt 里** |
| **伪造 thread_id 读取他人会话** | `resolve_thread_id` 强制前缀 `{user_id}_{role}` 匹配，不匹配一律回落本身份默认会话；已有 6 条专项单测 |
| **Agent 越权发通知** | `send_notification` 内置权限矩阵：学生/骑手只能通知 admin；定向用户仅 admin 可用 |
| **模型编造业务事实** | 工具返回结构化真实数据；prompt 明令禁止编造订单号/金额/轨迹；补偿金额由平台规则决定，Agent 不承诺 |
| **模型异常导致 500** | 路由三级降级 + 子 Agent 异常兜底 + 路由层全局 try/except，最终都返回 HTTP 200 的友好文案 |
| **推理模型思考链泄漏给用户** | `strip_think` 统一剥离 `<think>…</think>`（含未闭合截断） |
| **响应体泄露内部堆栈** | 对外只返回友好文案，真实异常写服务端日志 |

### 6.3 已知安全待办

| 项 | 现状 | 建议 |
|---|---|---|
| `AUTH_SECRET` 默认值 | 代码内有兜底默认值 | 生产环境必须在 `.env` 覆盖 |
| SMTP 邮箱授权码 | 存在于配置文件 | 移入环境变量并轮换，不入库不进包 |
| `MINIMAX_API_KEY` | 仅在 `.env` | 保持不入库；生产建议加网关限流与调用配额 |
| 会话记忆持久化 | 内存态，重启丢失 | 生产切 `RedisSaver` 后可做审计留痕 |

---

## 7. 部署架构

```
华为云 ECS（117.78.5.155）
  ├── /opt/campus_delivery/          项目代码
  ├── /root/venv/                    Python 3.11.6 虚拟环境
  ├── systemd campus-delivery.service 守护进程
  └── :8000                          对外提供 API + 前端静态资源

华为云 RDS MySQL（内网）      → campus_delivery 库（12 张表）
华为云 DCS Redis（内网）      → 通知流 + 热点缓存
外部 MiniMax API（OpenAI 兼容）→ LLM 推理（出网访问）
```

### 7.1 3.0 部署新增步骤

```bash
cd /opt/campus_delivery
pip install langchain==1.4.6 langchain-openai==1.7.2 langgraph==1.2.16 langgraph-checkpoint==4.3.0
```

`.env` 新增配置：

```bash
MINIMAX_API_KEY=<你的 key>
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=minimax-m3
MINIMAX_MAX_TOKENS=8192
```

验证：

```bash
curl -s http://127.0.0.1:8000/api/meta
# 期望看到 redis_mode=redis、database=华为云 RDS MySQL
```

### 7.2 一键开通脚本

`scripts/provision.py` 支持子命令：

| 命令 | 作用 |
|---|---|
| `probe` | 只读列出可用 project / VPC / Subnet / RDS flavor / DCS spec |
| `create-rds` / `create-dcs` | 默认 `dry_run` 演练，加 `--apply` 才真正创建 |
| `wait <instance_id>` | 轮询状态直到 `ACTIVE` 并打印内网连接串 |

### 7.3 本地自测脚本

| 脚本 | 用途 |
|---|---|
| `scripts/check_assistant.py` | 不起 Web 服务，直接驱动 LangGraph 图，打印每轮路由结果、调用过的工具、最终回复，并统计本次新增的通知条数（验证 `send_notification` 真的落库） |
| `scripts/check_minimax_tools.py` | 校验 MiniMax 端点的 function calling 与工具 schema 兼容性 |

---

## 8. 可量化指标

### 8.1 工程指标

| 指标 | 数值 | 口径 |
|---|---|---|
| 后端规模 | 45 个 Python 文件 / 4073 行 | `app/` |
| 自动化测试 | **56 项可收集**；受限环境下实测 48 项通过（agents 35 + sessions 13），api 8 项因环境禁用本地 socket 无法启动 TestClient | `pytest --collect-only` / `pytest -q` |
| 路由模块 | 10 个 | `app/routers/` |
| 业务接口 | 45 个（另加 `/api/meta`、`/health`） | 见附录 A |
| 服务模块 | 12 个 | `app/services/` |
| 数据表 | 12 张 | SQLAlchemy ORM |
| 前端 Tab | 13 个定义，按角色过滤可见 | `frontend/index.html` |
| Agent 工具 | 4 个 | 3 异常类 + 1 通知类 |
| 路由降级层数 | 3 级（function calling → JSON 文本 → 关键词） | `app/agents/graph.py` |
| 会话隔离维度 | 2 维（user_id × role） | `resolve_thread_id` |

### 8.2 业务指标

| 指标 | 数值 | 说明 |
|---|---|---|
| 异常补偿响应 | 上报后 **600 秒**（10 分钟）超时自动触发，入账 < 1 秒 | `ANOMALY_TIMEOUT_SECONDS` / `COMPENSATION_AMOUNT` |
| 默认补偿金额 | 5.0 元 | 自动入账学生虚拟余额并原路退款 |
| 轨迹节点 | 6 节点全链路（时间戳 + 经纬度 + 配送员） | `constants.NODE_TYPES` |
| 单车装载 | 40 单/车 | `VEHICLE_CAPACITY` |
| 人力分配 | 人均 30 单 | `COURIER_CAPACITY` |
| 照片审核阈值 | 亮度 < 30 拒收；拉普拉斯方差 < 60 拒收；颜色熵 > 7.0 拒收 | `image_audit.audit_image` |
| 颜色熵区分度 | 噪声 14.6 vs 正常 1.3（> 10 倍） | 实测样本 |
| 异常状态机 | 5 态 | pending → investigating → located → compensated → resolved |
| 异常类型 | 2 类 | lost / not_delivered |

---

## 9. 代码结构索引（3.0 相关）

```
campus_delivery/
├── app/
│   ├── agents/                          ← ★ 3.0 智能体层
│   │   ├── graph.py                     Supervisor 图 + 三级降级路由
│   │   ├── llm.py                       MiniMax → LangChain ChatModel 工厂
│   │   ├── context.py                   contextvars 传递 db session / 登录身份
│   │   ├── prompts.py                   system prompt 集中管理
│   │   ├── text_utils.py                <think> 剥离 + JSON 提取
│   │   ├── agents/anomaly_agent.py      异常应急 ReAct 子 Agent
│   │   └── tools/
│   │       ├── anomaly_tools.py         query_order_log / report_anomaly / list_my_anomalies
│   │       └── notification_tools.py    send_notification
│   ├── routers/
│   │   └── assistant.py                 ★ 3.0 新增：/api/assistant/chat
│   ├── services/                        12 个业务服务（3.0 未改动算法）
│   ├── models.py                        12 张表（3.0 未新增）
│   ├── security.py                      HMAC token
│   ├── config.py                        环境变量配置
│   ├── redis_client.py                  DCS Redis + 进程内降级
│   └── main.py                          应用装配 + /api/meta
├── frontend/                            Vue3 单页（13 Tab）
├── tests/
│   ├── test_agents_graph.py             35 项
│   ├── test_assistant_sessions.py       13 项
│   └── test_api.py                       8 项
├── scripts/
│   ├── provision.py                     华为云 RDS/DCS 一键开通
│   ├── check_assistant.py               AI 助手真实调用自测
│   └── check_minimax_tools.py           function calling 兼容性校验
├── docs/design.md                       2.0 设计文档（历史版本）
└── docs/design-3.0.md                   本文档
```

---

## 10. 已知边界与演进方向

本节如实列出 3.0 尚未实现或有限制的部分，供评审与后续迭代参考。

### 10.1 已实现但有明确限制

| 项 | 现状 | 影响 | 后续动作 |
|---|---|---|---|
| **业务子 Agent 数量** | 目前只有 `anomaly_agent` 一个真实业务子 Agent；`supervisor` 与 `finalize` 是编排节点 | 订单分拣、路径规划仍是确定性算法 + 前端按钮调用，未接入自然语言入口 | 新增分拣/调度 Agent 时沿用现有 tools + context 模式 |
| **checkpoint 持久化** | `MemorySaver`，进程内多轮记忆，**重启即丢** | 服务器重启后对话上下文不保留 | 换 `langgraph.checkpoint.redis.RedisSaver`（DCS），无需改表 |
| **OCR 校验** | 由 `HW_OCR_ENABLED` 控制，**可选挂载**；未启用时只做黑/花/模糊判定 | 默认部署下照片只验质量，不验单号/寝室号 | 生产开启并做好超时与降级监控 |
| **高德 Key** | 未配置时降级为 haversine 直线距离 | 路线不再是真实路网，路线图上会出现直线段 | 生产配置 `AMAP_KEY` |
| **通知渠道** | `app_push` 为主要通道，落库 + Redis 推送；短信/站内为枚举预留 | 未真正对接短信网关 | 需要时再接 |
| **邮箱验证码** | SMTP 直连 QQ 邮箱 | 依赖单账号配额 | 生产建议换邮件服务 |
| **API 测试运行环境** | `test_api.py` 依赖 `starlette.TestClient`，需本地 socket 支持 | 禁用本地 socket 的环境中 8 项无法启动 TestClient（`WinError 10051`） | CI 与开发机放开本地回环端口即可，与业务代码无关 |

### 10.2 版本状态

- 3.0 代码**尚未提交 Git**：当前分支 `main`，最后一次提交为 2.0 快照 `7cc1b22`；`app/agents/`、`app/routers/assistant.py`、`tests/test_agents_graph.py`、`tests/test_assistant_sessions.py` 均为未跟踪文件；
- 建议提交前清理临时脚本与本地数据文件（`campus_delivery.db`、`test_tmp.db`、`.merkle-snapshot.json`、`.env`）。

### 10.3 下一期候选方向

1. **分拣与调度 Agent**：让「批量导入后自动装箱排线」可以用自然语言触发，但算法仍走 `dispatch_service`；
2. **多轮对话持久化**：接 DCS Redis 后支持跨设备继续会话；
3. **订单 Agent**：只读解释型 Agent，回答「我的订单到哪了」，复用 `query_order_log`；
4. **A/B 与灰度**：Supervisor 路由策略可插拔，便于对比关键词兜底与模型路由的准确率。

---

## 附录 A：接口清单速查

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录并签发 token |
| POST | `/api/auth/register` | 注册 |
| POST | `/api/auth/send-code` | 发送邮箱验证码 |
| POST | `/api/auth/change-password` | 修改某角色密码 |
| POST | `/api/auth/update-profile` | 更新资料 |
| POST | `/api/auth/reset-password` | 重置密码 |
| DELETE | `/api/auth/account` | 注销账号 |
| POST | `/api/orders` | 新建订单 |
| POST | `/api/orders/batch` | 批量导入 |
| GET | `/api/orders` | 订单列表（按角色过滤） |
| GET | `/api/orders/{id}` | 订单详情 |
| PATCH | `/api/orders/{id}/status` | 状态流转（自动生成轨迹节点） |
| GET | `/api/tracking/{order_id}` | 订单轨迹 |
| POST | `/api/tracking/nodes` | 手工补录轨迹节点 |
| GET | `/api/tracking/log/{order_no}` | 订单完整日志 |
| POST | `/api/photos/upload` | 上传照片并审核 |
| GET | `/api/photos/{id}` | 照片与审核结果 |
| POST | `/api/anomalies` | 上报异常 |
| GET | `/api/anomalies` | 异常列表 |
| GET | `/api/anomalies/{id}/contacts` | 关联骑手/学生联系方式 |
| POST | `/api/anomalies/{id}/locate` | 定位异常环节 |
| POST | `/api/anomalies/{id}/handle` | 追加处理留痕 |
| POST | `/api/anomalies/{id}/compensate` | 手动触发补偿 |
| POST | `/api/anomalies/{id}/resolve` | 闭环解决 |
| POST | `/api/anomalies/check-timeouts` | 超时扫描（触发自动补偿） |
| POST | `/api/dispatch/plan` | 生成并持久化调度方案 |
| GET | `/api/dispatch/plan` | 预览调度方案 |
| GET | `/api/dispatch/trips` | 最近车次 |
| GET | `/api/dispatch/staff` | 最近人力分配 |
| POST | `/api/notifications/subscribe` | 订阅通知 |
| GET | `/api/notifications/subscriptions` | 订阅列表 |
| GET | `/api/notifications/history` | 可见通知历史（按身份过滤） |
| POST | `/api/notifications/{id}/read` | 标记已读 |
| POST | `/api/notifications/read-all` | 全部已读 |
| DELETE | `/api/notifications/{id}` | 删除（仅自己可见状态） |
| POST | `/api/notifications/test` | 测试推送 |
| GET | `/api/admin/users` | 人员列表 |
| GET | `/api/admin/users/{id}` | 人员详情 |
| POST | `/api/admin/users/{id}/reset-password` | 重置密码 |
| DELETE | `/api/admin/users/{id}/credentials/{role}` | 解绑角色 |
| DELETE | `/api/admin/users/{id}` | 删除人员 |
| GET | `/api/admin/users/{id}/orders` | 人员关联订单 |
| GET | `/api/balance/transactions` | 余额流水 |
| POST | `/api/balance/recharge` | 充值（管理员） |
| **POST** | **`/api/assistant/chat`** | **★ 3.0：AI 助手对话** |
| GET | `/api/meta` | 云服务与运行状态 |
| GET | `/health` | 健康检查 |

## 附录 B：Agent 工具契约

| 工具 | 参数 | 返回 | 前置条件 |
|---|---|---|---|
| `query_order_log` | `order_no: str` | JSON：订单 + 轨迹节点 + 异常记录 | 订单存在且当前身份有权 |
| `report_anomaly` | `order_no: str`, `anomaly_type: str`（`lost` / `not_delivered`）, `description: str = ""` | JSON：异常 id / 状态 | 订单存在且有权；建议先调 `query_order_log` |
| `list_my_anomalies` | 无 | JSON 数组：本人上报的异常 | 已登录 |
| `send_notification` | `target: str`, `title: str`, `content: str`, `order_no: str = ""` | JSON：通知 id / 目标 / 是否发送 | 目标合法；定向用户仅 admin；`order_no` 需有权 |

---

> 文档版本 v3.0（2026-10-26）　编制依据：`campus_delivery` 工作区代码实测统计　关联仓库：`https://github.com/yyxz0611/campus_delivery`