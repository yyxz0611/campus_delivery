---
name: nl2sql_gate
description: 把自然语言问题安全地转成只读 SQL 并执行，含三级降级与五道安全闸门。当需要实现自然语言查库、给分析模块加 LLM 生成 SQL 能力、或评审 SQL 生成链路是否会被注入/误删时使用。
---

# nl2sql_gate

自然语言进、结果集出。核心不是「能不能生成 SQL」，而是**生成错了会不会把库搞坏**。

## 何时使用

- 实现分析模块的自然语言查询入口
- 给已有 NL2SQL 链路补安全校验
- 排查「AI 生成的 SQL 为什么删了数据」这类事故

## 三级降级（必须按顺序）

```
问题 → [L1 模板命中] → 命中则执行
         ↓ 未命中
       [L2 LLM 生成] → 过闸门 → 执行 → 失败则回退
         ↓ 失败
       [L3 拒答] → 返回「无法理解」+ 推荐问题列表
```

### L1 模板匹配

在语义层 GLOSSARY 中维护高频问题模板，形如：

```python
TEMPLATES = [
    {"pattern": r"(各|每个)楼栋.*(超时|迟到)", "sql": "SELECT dorm_building, COUNT(*) ..."},
]
```

命中即执行，零 LLM 成本、零不确定性。**先做 L1 再做 L2**，
因为高频问题占绝大多数，模板能覆盖的部分根本不该交给模型。

### L2 LLM 生成

送给模型的上下文必须包含三样，缺一样都会显著降低准确率：

1. 语义层中的相关表与字段中文别名
2. 同域 2–3 条示例「问题 → SQL」对
3. 硬约束：只输出 SQL、只读、必须带 LIMIT

模型输出**不得直接执行**，必须先经解析：

```python
match = re.search(r"```sql\s*(.*?)```", text, re.S)
sql = match.group(1) if match else text.strip()
```

模型可能返回解释性文字、多个 SQL、或 markdown 包裹，解析失败即视为 L2 失败。

### L3 拒答

返回固定话术 + 可用问题示例。**不要重试超过 2 次**，重试会把延迟从秒级拖到分钟级。

## 五道安全闸门（顺序不可调换）

| # | 闸门 | 规则 |
|---|---|---|
| 1 | 语句类型 | 必须 `SELECT` 或 `WITH` 开头，否则拒绝 |
| 2 | 关键字 | 命中 `insert/update/delete/drop/alter/create/attach/detach/pragma/replace/vacuum` 即拒绝 |
| 3 | 注释 | 含 `--` 或 `/*` 即拒绝（注释可绕过闸门 2，例如 `DELETE/**/FROM`） |
| 4 | 表白名单 | `FROM` / `JOIN` 后出现的表必须全部在白名单内 |
| 5 | 行数上限 | 无 `LIMIT` 时强制追加 `LIMIT 200`，结果集再 `fetchmany(200)` 兜底 |

闸门 3 最容易被忽略：很多人只做关键字匹配，结果 `DELETE\-\- x` 或 `SELECT 1; DROP TABLE` 直接穿过去。
**多语句检查也要做**：语句体内部出现 `;` 即拒绝。

## 审计

每次查询写一条 `ops_query_log`：

```
question / generated_sql / status(ok|rejected|failed) / reject_reason / row_count / elapsed_ms
```

审计表必须可查——「AI 生成过什么危险语句」这个问题，只能靠审计回答。

## 自检用例（必须全部通过）

```
"SELECT id FROM orders"                      → 放行
"DELETE FROM orders"                         → 拒绝（闸门 1）
"SELECT 1; DROP TABLE orders"                → 拒绝（闸门 2/多语句）
"SELECT * FROM orders -- comment"            → 拒绝（闸门 3）
"SELECT * FROM sqlite_master"                → 拒绝（闸门 4）
"select * from orders"                       → 放行且自动补 LIMIT
```

把这段用例写进 `tools/selfcheck.py` 的 `check_sql_gate`，每次改动自动回归。

## 禁止事项

- 不得把模型输出的 SQL 直接 `execute`
- 不得为了「用户体验」放宽闸门，例如允许 `UPDATE` 只影响一行
- 不得用字符串拼接参数，必须走参数化查询
- 不得在审计里记录完整 SQL 文本以外的敏感数据（手机号、口令）