---
name: router_auth_audit
description: 扫描 FastAPI 全部路由的鉴权覆盖情况，识别缺失鉴权或角色不匹配的接口，生成补丁并在改动后跑回归自检。当需要收口管理员接口权限、审计越权风险、或给新模块补统一鉴权依赖时使用。
---

# router_auth_audit

找出「谁能不登录就调用的接口」。这类漏洞不会报错、不会影响功能，
只会在某天被人从外部打穿——所以只能靠结构化扫描，不能靠肉眼。

## 何时使用

- 管理端接口需要收口鉴权
- 新增模块涉及敏感数据，需要复核权限边界
- 上线前做一次越权面审计

## 执行步骤

### 1. 静态扫描（不启动服务）

直接解析 `app/routers/*.py`，对每个 `@router.{method}` 装饰的函数记录四件事：

| 采集项 | 用途 |
|---|---|
| 方法 + 完整路径 | 与路由基线对齐，确认没漏扫 |
| 函数签名里的 `Depends(...)` | 判断是否挂了鉴权依赖 |
| 函数体内是否调用 `parse_token` | 判断是否是手写鉴权 |
| 函数体内是否读取 `x_auth_token` | 区分「读了 token」与「根本没读」 |

扫描用 AST 或正则均可，但**必须覆盖全部 45 个接口**——
数量对不上说明扫描漏了，先修扫描器再说结论。

### 2. 三分类

- **A 类·有鉴权**：挂了依赖，或函数体内调用 `parse_token` 且对结果做了判断
- **B 类·裸奔**：完全不读 token，任何人可调
- **C 类·读了不判**：读了 token 但没校验角色，只要带任意合法 token 就能调

C 类最隐蔽，手工审查最容易漏。判定标准：读完 `parse_token` 后，
必须出现针对 `role` 或 `user_id` 的比较或分支，否则归 C 类。

### 3. 输出审计报告（先报告，后改代码）

```markdown
| 接口 | 类别 | 风险 | 建议 |
|---|---|---|---|
| DELETE /api/admin/users/{id} | B | 高 | 挂 require_admin |
| GET /api/anomalies/{id}/contacts | B | 高 | 挂 require_role |
```

**不要跳过报告直接改**。报告是给人做决策的，人工确认哪些属于设计意图
（例如 `/api/auth/login` 本来就该裸奔）。

### 4. 生成补丁

统一依赖写在 `app/security.py`：

```python
def require_role(*roles: str):
    def dependency(x_auth_token: str | None = Header(None)):
        current = parse_token(x_auth_token)
        if not current:
            raise HTTPException(401, "未登录")
        if roles and current[1] not in roles:
            raise HTTPException(403, "无权访问")
        return current
    return dependency
```

接入方式：**只加 `dependencies=[...]` 或参数，不改路由函数体**。
如果必须改函数体，说明补丁设计有问题，回到第 3 步重新评估。

### 5. 回归

```
python tools/selfcheck.py
```

重点看两项：

- 路由基线：**必须仍是 45 个，新增 0、丢失 0**。变少说明改坏了
- SQL 闸门：权限改动不应影响它，若失败说明误改了共享代码

### 6. 补反向测试

每个新挂鉴权的接口，至少补两条：

```python
def test_admin_requires_token():        # 无 token → 401
def test_admin_rejects_rider():         # 骑兵 token → 403
```

只测「管理员能进」没有意义——**权限的价值在拒绝**。

## 判断口径

- 401 = 没登录（缺 token 或 token 无效）
- 403 = 登录了但角色不对
- 不要把 403 写成 404，那会让排查权限问题时无从下手

## 禁止事项

- 不得用「前端会隐藏按钮」作为不做后端校验的理由
- 不得把统一鉴权依赖挂在 `APIRouter(prefix=...)` 上而不确认该 router 下所有接口都需要
- 不得在扫描数量与基线不符时直接下结论，先修扫描器