# AGENTS.md — 校园外卖配送对接平台 · 工程上下文与硬性约束

> 本文件是码道（CodeArts Agent）在本仓库工作时的工程上下文。
> 目的：把「项目的已知事实」前置给 AI，抑制臆测式生成，使每次代码变更都能被回归测试验证。
> 维护约定：架构、表结构、鉴权模型发生变化时，同步更新本文件对应小节。

---

## 1. 项目定位

面向高校最后一公里的外卖履约协同系统。三类角色协作：

- **学生**：下单、查询进度、查看通知
- **骑手**：接单、上报 GPS 轨迹、上传交接照片
- **管理员**：按楼栋聚合订单生成车次、处理异常、发放补偿、管理用户

**明确不做的事（不要生成相关代码）**：

- 真实支付。微信支付个人主体不可行，只有虚拟余额（充值 / 补偿 / 退款 / 消费流水）。
- 对接美团 / 饿了么 / 达达开放 API。个人无企业资质，路径是自建接单入口 + 小票 OCR + 骑手 GPS 上报。

---

## 2. 技术栈与运行环境

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + SQLAlchemy 2.0（`Mapped` / `mapped_column` 风格） |
| 数据库 | SQLite（本地开发）/ MySQL（华为云 RDS），由 `.env` 的 `DATABASE_URL` 切换 |
| 缓存 | 华为云 DCS Redis（可选，未配置时降级为进程内） |
| 前端 | Vue3 + 传统 CSS，CDN 引入，无构建步骤、无 npm |
| 测试 | pytest |

```bash
uvicorn app.main:app --reload      # 本地启动
pytest -q                          # 全量回归
python scripts/align_schema.py     # 表结构对齐（新增字段后必跑）
```

## 3. 目录与职责

```
app/
  main.py          # 应用装配：10 个 router 挂载 + /static 静态目录
  config.py        # 环境变量与配置读取
  database.py      # engine / SessionLocal / get_db / Base
  models.py        # 12 张表的 ORM 定义（唯一数据模型来源）
  schemas.py       # Pydantic 出入参模型
  security.py      # make_token / parse_token（HMAC token）
  redis_client.py  # Redis 连接与降级
  huawei.py        # 华为云 OCR 等 SDK 封装
  constants.py     # 领域常量（配送节点类型、订单状态、角色名）
  routers/         # 10 个路由模块：orders/auth/tracking/photos/anomalies/
                   #   dispatch/notifications/admin/balance/assistant
  services/        # 12 个业务服务，路由只做参数装配，业务逻辑在 service 层
  agents/          # LangGraph 编排（Supervisor → 业务子 Agent）
frontend/          # Vue3 单页应用
tests/             # pytest：test_api / test_agents_graph / test_assistant_sessions
scripts/           # align_schema.py 等运维脚本
```

**分层纪律**：`routers` 不写业务逻辑，只做参数校验与调用 `services`；`services` 不感知 HTTP 上下文（不接收 `Request`）。

---

## 4. 数据模型（12 表）

| 表 | 用途 | 关键约束 |
|---|---|---|
| `users` | 平台自然人，按手机号唯一 | `phone` unique |
| `user_credentials` | 角色凭据，一人多角色各一套密码 | `(user_id, role)` unique |
| `orders` | 外卖订单 | `order_no` unique，`status`/`rider_user_id` 索引 |
| `delivery_nodes` | 配送轨迹节点（6 类节点） | 按 `order_id` 聚合 |
| `photo_records` | 交接照片与审核结果 | `audit_metrics` / `audit_result` 为 JSON |
| `anomalies` | 异常与应急闭环 | `status` 五态流转 |
| `vehicle_trips` | 运输车车次与路线 | `trip_no` unique，`route` 为 JSON |
| `staff_shifts` | 宿舍楼下人力分配 | 按 `dorm_building` 索引 |
| `notification_subscriptions` | 通知订阅 | |
| `notifications` | 持久化通知 | `target_role` / `target_user_id` 索引 |
| `notification_user_states` | 每人已读 / 删除状态 | `(notification_id, user_id)` unique |
| `balance_transactions` | 余额流水 | `amount` 正数入账、负数扣减 |

**不得凭印象写的枚举值**（以 `constants.py` 与模型注释为准）：

- 订单状态：`pending` 等，写代码前先读 `constants.py`
- 配送节点：`pickup` / `external_handover` / `internal_transport` / `site_arrival` / `dorm_delivery` / `completed`
- 异常类型：`lost` / `not_delivered`；异常状态：`pending` / `investigating` / `located` / `compensated` / `resolved`
- 角色：`admin` / `rider` / `student`

---

## 5. 硬性约束（违反即视为本次变更失败）

**R1 · 数据库变更必须补迁移**
`Base.metadata.create_all()` 只会建新表，**不会给已有表补列**。任何在 `models.py` 新增字段的变更，必须同时运行 / 更新 `scripts/align_schema.py`，否则线上表现为「前端报 not valid JSON」，实际是后端 500（列不存在）。排查此类报错，先查后端日志，不要先查前端。

**R2 · 鉴权走 header，不引入新机制**
token 从 `x-auth-token` 请求头读取，用 `security.parse_token()` 解析为 `(user_id, role)`。不引入 JWT、OAuth、Session Cookie。

**R3 · 账号模型不可简化**
一人多角色、每角色独立密码（`users` + `user_credentials` 拆表）。同一用户的不同角色密码**必须互不相同**，注册 / 改密 / 重置三处都要校验，否则登录身份产生歧义。密码使用 PBKDF2 哈希，6–12 位字母数字。

**R4 · 前端沿用既有风格**
传统 CSS，新页面必须与已有页面的类名、配色、间距保持一致；不引入 Tailwind、UI 组件库、构建工具。命名统一 snake_case。

**R5 · 测试是回归闸门**
任何改动完成后必须 `pytest -q` 通过。新增接口必须补测试，新增权限判断必须补一条「越权应被拒绝」的反向用例。

**R6 · 不擅自增加依赖**
新增第三方包前必须先说明必要性并等待确认。当前 requirements 已覆盖 FastAPI / SQLAlchemy / LangChain 系列 / 华为云 SDK / pytest。

**R7 · 安全红线**
`.env` 含真实 AK/SK 与数据库口令，**任何情况下不得读取其值写入代码、日志、文档或提交**。`.env.example` 是唯一可公开的样例。订单接口对外不得返回 `customer_phone`。

---

## 6. 变更纪律（AI 必须遵守的工作流程）

**D1 · 先读后写**
修改任何文件前，先读取目标文件与它直接依赖的 `service`、`schema`。不得基于「这个项目应该有……」进行推断。

**D2 · 不臆测字段**
涉及数据库字段、接口路径、状态枚举时，必须先在 `models.py` / `schemas.py` / `constants.py` 中定位到实际定义，无法定位则明确说出「未找到」并停止，不要编造。

**D3 · 小步提交**
一次变更只做一件事，完成后立即提交，提交信息说明「改了什么 + 为什么」。跨模块改动拆成多次提交，便于回溯与回退。

**D4 · 改完必自检**
每次改动后必须执行 `python tools/selfcheck.py`，退出码为 0 才算完成。该脚本检查五项：语法编译、路由基线（45 个接口）、表清单（12 张表）、敏感信息、SQL 安全闸门。
新增接口会被自动放行；删除或修改已有接口签名会被拦截——确需改动时先 `tools/selfcheck.py --init` 重建基线，并在提交信息中写明原因。
需要回归时加 `--with-tests`，但沙箱环境 `test_api.py` 会因禁 socket 报 `WinError 10051`，属环境限制，不是代码缺陷。
涉及前端则实际打开页面确认。只报告「应当可用」不算完成。

**D5 · 边界如实说**
能力边界不能写成能力。已知边界（截至当前版本）：
- 超时补偿依赖订单状态触发，**没有后台定时巡检**
- `admin` 路由目前缺少统一鉴权依赖（待治理项，见 docs/ai-coding）
- OCR 为可选挂载，未配置时降级为手动录入
- 会话检查点为进程内实现，服务重启即丢

**D6 · 新功能以追加实现**
新增模块只允许「新建文件 + 在 `main.py` 追加一行 `include_router`」，不得改动已有 45 个接口的路由函数签名与实现。需要复用逻辑时调用 `services` 层，不要复制粘贴，也不要顺手重构无关代码。

---

## 7. 已知陷阱（真实踩过，不要再踩）

1. **Windows 批量编译命令行超长**：把所有后端文件拼进一条编译命令会失败，逐个编译。
2. **中文路径 + heredoc**：在 Windows PowerShell 下用 heredoc 写文件常无输出，改用显式写文件。
3. **高德路线断线**：折线首尾是吸附点，不是手填坐标；`current` 必须取吸附点。
4. **前端 `not valid JSON`**：多为后端 500，先看后端日志。
5. **同手机号 = 同 user_id**：测试「定向通知」时必须用不同手机号，否则两个角色会同时收到。

---

## 8. 输出规范

- 代码风格：snake_case，类型注解齐全，`from __future__ import annotations`
- 注释：仅在被要求时添加
- 报告变更时给出「文件:行号」，便于核对
- 不确定的信息标注「需核实」，不得含糊表述为已确认