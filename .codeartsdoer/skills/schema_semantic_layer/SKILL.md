---
name: schema_semantic_layer
description: 从数据库真实结构生成中英双语语义层，供自然语言转 SQL 使用。当需要为业务系统建立表/字段/枚举的中文映射、新增分析类查询能力、或校验语义层与数据库是否一致时使用。禁止凭 models.py 注释推断枚举值。
---

# schema_semantic_layer

把 12 张物理表翻译成「业务人员能问、机器能查」的语义层。语义层是 NL2SQL 的唯一事实来源，
一旦它与真实数据不一致，生成出来的 SQL 会静默查错，比报错更危险。

## 何时使用

- 需要新增「用中文提问查数据」的能力
- 需要给某张表补中文别名或枚举释义
- 需要校验现有语义层是否与数据库漂移

## 执行步骤

### 1. 建立数据全景

调用 MCP 工具 `list_tables`，确认表的实际存在与行数。

**不要跳过这一步直接读 `models.py`**：模型定义不等于库里真实存在的表，
库可能还没跑 `align_schema.py`。

### 2. 逐表获取真实结构

对每张表调用 `describe_table`，记录字段名、类型、非空、主键。

### 3. 枚举值必须实测

对含枚举语义的字段（如 `orders.status`、`anomalies.anomaly_type`），
调用 `run_readonly_query` 执行：

```sql
SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC
```

**判定规则**：语义层里出现的每个枚举值，必须能在 `DISTINCT` 结果中找到；
反之，结果里的每个值也必须被语义层覆盖。两边对不上就是漂移，必须先修正再往下走。

不允许根据 `models.py` 的行内注释推断枚举——注释是历史遗留，可能与数据不符。

### 4. 生成语义层

产出 `app/services/ops_semantic.py`，结构固定为四段：

```python
TABLES = {"orders": {"label": "订单", "desc": "..."}}
COLUMNS = {"orders": {"order_no": "订单号", "dorm_building": "宿舍楼栋"}}
ENUMS = {"orders.status": {"pending": "待接单", "picked": "已取货"}}
GLOSSARY = {"超时": "...", "楼栋": "...", "运力": "..."}
```

GLOSSARY 收录业务黑话，这是让自然语言能被正确理解的关键——
「超时」到底指 `delivered_at > expected_delivery_at` 还是状态为 `abnormal`，必须在这里写死。

### 5. 校验覆盖率

新增 `tools/check_semantic.py`，断言：

- 12 张表全部有 `TABLES` 条目，覆盖率 100%
- 每张表的每个字段都有 `COLUMNS` 中文别名
- 每个枚举字段的取值集合与数据库 `DISTINCT` 完全一致
- 每个指标在 GLOSSARY 里有唯一定义，不存在两种解释

任一断言失败即退出码 1，不产出语义层。

## 输出要求

交付时给出三个数字，缺一不可：

- 表覆盖率：x/12
- 字段覆盖率：x/y（y 为全部字段数）
- 枚举一致率：x/y（y 为枚举字段数）

## 禁止事项

- 不得在语义层里写「约」「大概」「一般情况下」这类模糊表述
- 不得让同一个中文词对应两个不同字段
- 不得为了覆盖率把没有中文名的字段留空占位，必须给出真实业务含义