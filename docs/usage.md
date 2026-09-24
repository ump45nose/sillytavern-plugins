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

本地开发省略 OAuth 配置时，`/mcp` 无鉴权，方便用五个真实联系人验证字段。公网部署必须完整配置 Authelia OIDC 和用户名白名单。

MCP 提供人物、互动、Fact、Reminder 与周绩效共十四个工具。所有修改工具返回实体 ID 和修改前后摘要；不提供 SQL 工具，也不会自动发送建议话术。

## Mac Connector

为 Connector 单独创建不提交到 Git 的 `connector.env`：

```dotenv
WECHAT_SOURCE=chatlog
CHATLOG_EXECUTABLE=/Users/your-name/Library/Application Support/personal-crm/bin/chatlog-keeper
CHATLOG_EXPECTED_SHA256=replace-with-release-sha256
CHATLOG_SCOPES=/Users/your-name/Library/Application Support/personal-crm/wechat/whitelist-scopes.json
CHATLOG_SCOPE_MODE=all_direct
CHATLOG_PAGE_SIZE=200
CHATLOG_WINDOW_SECONDS=86400
CHATLOG_OVERLAP_SECONDS=300
WECHAT_FACT_EXTRACTION=true
CHATLOG_POLL_SECONDS=60
CHATLOG_TIMEOUT=120
CRM_WEBHOOK_URL=https://crm.example.com/api/v1/webhooks/wechat
CRM_WEBHOOK_TOKEN=replace-with-webhook-secret
CRM_CHECKPOINT=/Users/your-name/Library/Application Support/personal-crm/checkpoint.json
WECHAT_CONTACTS=visible_wechat_id_alice,visible_wechat_id_bob
WECHAT_SINCE=2026-06-06T00:00:00Z
```

`CHATLOG_SCOPES` 是权限 `0600` 的本地 JSON 数组，每项包含
`requested_id/person_name/account_id/conversation_id/conversation_type`。其中
`requested_id` 必须与 `WECHAT_CONTACTS` 完全一致；账号和内部会话 ID 只留在 Mac，
不会写入 Webhook。`CHATLOG_SCOPE_MODE=all_direct` 会从本机目录枚举所有单聊，并沿用
`CHATLOG_SCOPES` 中已有会话的人物映射；此模式忽略 `WECHAT_CONTACTS`。群聊不纳入。
二进制应从已审计 Release 固定到私有目录，并配置 SHA-256。

先做不推进 checkpoint 的 dry run：

```bash
CRM_ENV_FILE=/absolute/path/connector.env uv run personal-crm-wechat --dry-run
```

确认输出只有数量和状态后，再去掉 `--dry-run`。常驻模式使用
`personal-crm-wechat --watch`。Connector 按一天窗口回填并保留五分钟重叠；只有 NAS
对整个批次（包括空窗口）返回成功且无错误项时，才会原子推进 checkpoint。
chatlog 读取失败、NAS 5xx 或进程重启均不会丢失水位。

Connector 将原始 `content` 以“消息内容：”前缀写入 NAS 的互动记录；不会在日志和
checkpoint 中保存正文。MCP `get_daily_chat_records` 可按业务日分页取回全部聊天原文，
Connector 不负责生成语义摘要。`WECHAT_FACT_EXTRACTION=true` 会启用
高置信规则抽取器：仅处理对方明确自述的偏好、边界、人生事件、组织和联系方式，
并只外发受限结构化 Fact；出站消息、卡片、链接和超长内容不抽取。抽取器通过独立
Protocol 隔离，后续可替换成本地模型或 Agent。
启用时还会为每个实际出现消息的白名单会话生成一个可幂等去重的 `contact` Fact，
用于记录微信来源身份并验证 Fact 链路；它不包含内部账号或会话 ID。
