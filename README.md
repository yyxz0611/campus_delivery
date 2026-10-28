# 校园外卖配送对接平台（校内外精准对接 · 点对点可追溯）

一个基于 **FastAPI + Vue3 + 华为云（RDS / DCS Redis / OCR 预留）** 的校园外卖配送对接系统，解决「校外外卖 → 校内配送」交接不透明、时间不可控、丢失难追溯的痛点，实现：

- 配送路径/时间精准可控（分钟级对接）
- 订单批量化管理 + 每个订单独有的配送轨迹日志
- 关键节点（校外交接、到寝）拍照上传 + 黑图/花图/模糊自动审核
- 异常应急：按订单号秒级定位，10 分钟无进度自动补偿退款
- 运输车车次/路线/宿舍人力统筹调度
- 送达通知订阅 + 全流程透明可追溯

---

## 一、核心功能

| 模块 | 能力 |
|------|------|
| 订单管理 | 新建/批量导入/搜索，状态机流转（待配送→取餐→交接→校内运输→楼下站点→配送→到寝完成） |
| 配送轨迹 | 每个节点含时间戳+经纬度+配送员，自动生成独有日志，全链路可追溯 |
| 照片审核 | 校外交接/到寝等节点拍照上传，PIL+numpy 真实检测黑图/花图/模糊，无效拒绝 |
| 异常应急 | 上报→定位问题环节→核查→超时自动补偿+退款反馈→闭环解决 |
| 统筹调度 | 按楼栋聚合订单、车容量装箱、贪心规划校内最优路线、宿舍人力分配 |
| 通知订阅 | APP/短信/站内订阅，Redis(DCS) 通知流实时推送 |

## 二、技术架构

```
Vue3(CDN) 单页 Demo
        │ HTTP
FastAPI (同步 SQLAlchemy 2.0)
  ├─ 订单 / 轨迹 / 照片 / 异常 / 调度 / 通知 路由
  ├─ 数据层：SQLite(本地) ⇄ 华为云 RDS MySQL/PostgreSQL(生产)
  └─ 缓存/消息：进程内缓存 ⇄ 华为云 DCS Redis(生产)
```

## 三、目录结构

```
campus_delivery/
├── app/
│   ├── main.py            # FastAPI 入口 + 云状态 /api/meta
│   ├── config.py          # 环境变量配置（RDS/Redis 一键切换）
│   ├── database.py        # SQLAlchemy 引擎与会话
│   ├── models.py          # ORM：订单/节点/照片/异常/车次/人力/订阅
│   ├── schemas.py         # Pydantic 模型
│   ├── constants.py       # 状态/节点常量
│   ├── redis_client.py    # DCS Redis 封装 + 进程内降级
│   ├── services/          # 业务服务层
│   └── routers/           # API 路由层
├── frontend/              # Vue3 单页 Demo（免构建）
├── tests/                 # pytest 端到端测试
├── static/uploads/        # 照片存储（生产可切 OBS）
├── Dockerfile / .dockerignore / requirements.txt / .env.example
```

## 四、本地快速启动

**运行环境**：Python 3.11 及以上（本项目在 Python 3.13 上开发与验证；ECS 部署使用 3.11.6），依赖见 `requirements.txt`。本地形态不需要 Node.js（前端为 CDN 引入的 Vue3，无构建步骤），也不需要任何云服务。

```bash
cd campus_delivery
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
# 打开 http://127.0.0.1:8080
```

> 本地默认 SQLite + 进程内缓存，无需任何云服务即可完整演示。
> 交互式 API 文档：`http://127.0.0.1:8080/docs`

运行测试：

```bash
pytest tests -v
```

---

## 五、华为云部署指南（想法到应用）

### 1. 一键开通（推荐）— 使用 provision 脚本

> 已基于华为云官方 SDK（`huaweicloudsdkiam/ocr/rds/dcs/vpc`）实现，凭证从 `.env` 的 `HW_AK/HW_SK/HW_REGION` 读取。

```bash
# 步骤 A：探测可用资源（只读，安全）
python scripts/provision.py probe
# 输出 project_id、可用 VPC / Subnet / RDS flavor(MySQL 8.0) / DCS flavor

# 步骤 B：把探测到的参数写进 .env
# RDS_FLAVOR_REF / RDS_AZ / RDS_VPC_ID / RDS_SUBNET_ID / RDS_PASSWORD
# DCS_SPEC_CODE / DCS_AZ / DCS_VPC_ID / DCS_SUBNET_ID / DCS_PASSWORD

# 步骤 C：演练创建（dry_run，不会真正扣费）
python scripts/provision.py create-rds
python scripts/provision.py create-dcs

# 步骤 D：确认无误后真正创建
python scripts/provision.py create-rds --apply
python scripts/provision.py create-dcs --apply

# 步骤 E：轮询状态直到 ACTIVE 并自动打印内网连接串
python scripts/provision.py wait <instance_id> --timeout 1800
```

### 2. OCR 真实照片审核

`.env` 设置 `HW_AK/HW_SK/HW_REGION=cn-north-4/HW_OCR_ENABLED=1` 后，照片上传接口会自动调用**华为云通用文字识别**，校验：

- 是否清晰可见**外卖单号**
- 是否包含**寝室号/环境背景**

未识别到单号或寝室号的照片会被拒收（质量审核未启用 OCR 时仅看黑/花/模糊）。OCR 调用失败自动回退质量审核，不影响主流程。

### 3. 手工开通路径

如果不便用 provision 脚本：

1. 控制台 → 关系型数据库 RDS → 创建 MySQL 8.0 实例 → 记录内网地址/端口/账号/密码。
2. 在 `.env` 填入：
   ```bash
   DATABASE_URL=mysql+pymysql://账号:密码@内网地址:3306/库名?charset=utf8mb4
   # 或 PostgreSQL
   DATABASE_URL=postgresql+psycopg2://账号:密码@内网地址:5432/库名
   ```
3. 控制台 → 分布式缓存 DCS → 创建 Redis 实例 → 记录内网地址/密码。
   ```bash
   REDIS_URL=redis://:密码@内网地址:6379/0
   ```

> 应用启动时自动 `create_all` 建表（12 张表：用户 / 角色凭据 / 订单 / 配送节点 / 照片审核 / 异常 / 车次 / 人力 / 通知订阅 / 通知 / 用户通知状态 / 余额流水）。
> 注意：`create_all` 只建新表、不给已有表补列；改动模型后需执行 `python scripts/align_schema.py`。
> Redis 未配置或连接失败时自动降级为进程内缓存，服务不中断。

### 4. 容器化构建

```bash
cd campus_delivery
docker build -t campus-delivery:1.0 .
docker run -p 8080:8080 --env-file .env campus-delivery:1.0
```

### 5. 部署上线（二选一）

**方式 A：云容器引擎 CCE（推荐）**

```bash
# 将镜像推送到华为云 SWR（软件仓库）
docker tag campus-delivery:1.0 swr.cn-xx.myhuaweicloud.com/<空间>/campus-delivery:1.0
docker push swr.cn-xx.myhuaweicloud.com/<空间>/campus-delivery:1.0
```
然后在 CCE 创建 Deployment（镜像=SWR 地址，环境变量来自 Secret，Service 暴露 8080，Ingress 配置公网访问）。

**方式 B：弹性云服务器 ECS**

```bash
# ECS 安装 Docker 后执行
docker run -d -p 80:8080 --env-file .env --restart=always swr.cn-xx.../campus-delivery:1.0
```

### 6. 华为云 CodeArts DevOps 流水线（高效开发实践）

1. **需求管理 Req**：将本场景拆解为需求/用户故事（订单、轨迹、照片审核、异常、调度）。
2. **代码托管 CodeHub**：推送本仓库至云端私有仓。
3. **构建流水线 Build**：CodeArts Build 执行 `docker build` 并推送镜像到 SWR。
4. **部署流水线 Deploy**：CodeArts Deploy 自动化部署到 CCE/ECS，并注入 RDS/Redis 连接串 Secret。
5. **测试 Test**：`pytest tests -v` 纳入 CI 门禁。

---

## 六、「想法到应用」价值闭环

| 阶段 | 华为云能力 | 本项目的使用 |
|------|-----------|-------------|
| 需求理解 | CodeArts Req（需求管理）| 场景拆解为 7 大功能模块 |
| 代码生成 | CodeArts 代码智能体 | 生成 FastAPI 服务层/路由/前端 |
| 项目构建 | CodeArts Build / SWR | Docker 镜像构建与制品推送 |
| 数据/缓存 | RDS + DCS Redis | 订单轨迹持久化 + 通知流/缓存 |
| 问题修复 | CodeArts TestPlan | pytest 8 项端到端测试全绿 |
| 部署上线 | CCE / ECS / CodeArts Deploy | 一键云上部署，可视化 Demo 对外展示 |