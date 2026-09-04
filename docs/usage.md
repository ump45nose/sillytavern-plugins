# 使用说明

## NAS 服务

`personal-crm-server` 同时提供健康检查、Webhook 和 Streamable HTTP MCP。数据库迁移必须在启动前显式执行：

```bash
uv run alembic upgrade head
uv run personal-crm-server
```

管理 CLI 仅用于恢复和诊断：

```bash
uv run personal-crm integrity
uv run personal-crm backup /safe/path/personal-crm-backup.db
```

本地开发省略 OAuth 配置时，`/mcp` 无鉴权，方便用五个真实联系人验证字段。公网部署必须完整配置 GitHub OAuth 和数字用户 ID 白名单。

MCP 提供人物、互动、Fact、Reminder 与周绩效共十四个工具。所有修改工具返回实体 ID 和修改前后摘要；不提供 SQL 工具，也不会自动发送建议话术。

## Mac Connector

为 Connector 单独创建不提交到 Git 的 `connector.env`：

```dotenv
WELINK_BASE_URL=http://127.0.0.1:18790
WELINK_PATH=/api/messages
CRM_WEBHOOK_URL=https://crm.example.com/api/v1/webhooks/wechat
CRM_WEBHOOK_TOKEN=replace-with-webhook-secret
CRM_CHECKPOINT=/Users/your-name/Library/Application Support/personal-crm/checkpoint.json
WECHAT_CONTACTS=wxid_alice,wxid_bob
WECHAT_SINCE=2026-06-06T00:00:00Z
WELINK_TIMEOUT=15
```

先做不推进 checkpoint 的 dry run：

```bash
CRM_ENV_FILE=/absolute/path/connector.env uv run personal-crm-wechat --dry-run
```

确认输出只包含摘要和结构化 Fact 后，再去掉 `--dry-run`。只有 NAS 对整个批次返回成功且无错误项时，Connector 才会原子推进 checkpoint。WeLink 断网、NAS 5xx 或进程重启均会重试相同数据。

Connector 不在日志或 Webhook 中放入原始 `text`/`content`。若 WeLink 没有提供独立摘要，它只生成“发生一次微信互动”的降级描述；Fact 只接受上游明确给出的结构化结果。
