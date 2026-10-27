# campus-db MCP Server

只读数据库 MCP，把项目数据库的表结构、样本数据与只读查询能力通过 MCP 协议暴露给 AI，
让 AI 在写 SQL、改模型、加接口前先拿到真实上下文，而不是从 `models.py` 反推字段。

零第三方依赖：只用 Python 标准库实现 stdio 上的 JSON-RPC 2.0。

## 为什么自建

- 本地环境未安装 `mcp` / `fastmcp` 包，自建可避免依赖安装与版本适配问题
- 只读白名单 + 脱敏是项目自身的合规要求，现成 server 无法定制
- 协议实现只用到 `initialize` / `tools/list` / `tools/call` / `ping`，约 280 行可控代码

## 工具

| 工具 | 作用 |
|---|---|
| `list_tables` | 列出 12 张白名单表及各自行数 |
| `describe_table` | 字段名、类型、非空、主键 |
| `sample_rows` | 抽取样本行（手机号、邮箱自动脱敏） |
| `run_readonly_query` | 执行 SELECT / WITH，自动追加 200 行上限 |

## 接入方式

把 `mcp_config.example.json` 中的 `<仓库根目录>` 替换为实际路径，写入 IDE 的 MCP 配置
（本项目为 `.codeartsdoer/mcp/mcp_settings.json`），重启 IDE 后生效。

```json
{
  "mcpServers": {
    "campus-db": {
      "command": "python",
      "args": ["<仓库根目录>/tools/mcp_db/server.py"]
    }
  }
}
```

## 安全边界

| 约束 | 实现 |
|---|---|
| 只读 | SQLite 以 `mode=ro` 打开；仅允许 `SELECT` / `WITH` 开头 |
| 禁 DDL/DML | 关键字黑名单拦截 `insert` `update` `delete` `drop` `alter` `create` `attach` `pragma` 等 |
| 禁注释 | 拒绝 `--` 与 `/*`，防止注释绕过关键字检查 |
| 表白名单 | `FROM` / `JOIN` 提及的表必须命中 12 张白名单 |
| 行数上限 | 无 `LIMIT` 时自动追加 `LIMIT 200`，`fetchmany(200)` 二次兜底 |
| 数据脱敏 | 手机号 → `138****0000`；邮箱 → `333***@qq.com`；`*TOKEN*` / `*SECRET*` 列整列打码 |
| 协议隔离 | 日志只写 stderr，stdout 仅输出协议消息 |

## 已验证

2026-10-27 本地管道实测：

- `initialize` 返回 `protocolVersion 2024-11-05` 与 tools 能力
- `tools/list` 返回 4 个工具
- `list_tables` 正确读出 12 张表及行数
- `describe_table orders` 读出 17 个字段
- `SELECT ... GROUP BY status` 正常返回 8 组，并自动补 `LIMIT 200`
- `DELETE FROM orders` 被拒绝：`只允许 SELECT / WITH 查询`
- 手机号脱敏为 `138****0000`，邮箱脱敏为 `333***@qq.com`