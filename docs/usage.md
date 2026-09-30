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
CHATLOG_PAGE_SIZE=200
CHATLOG_WINDOW_SECONDS=86400
CHATLOG_OVERLAP_SECONDS=300
WECHAT_FACT_EXTRACTION=true
CHATLOG_POLL_SECONDS=60
CHATLOG_TIMEOUT=120
CRM_WEBHOOK_URL=https://crm.example.com/api/v1/webhooks/wechat
CRM_WEBHOOK_TOKEN=replace-with-webhook-secret
CRM_CLIENT_ID=macbook-pro
CRM_ACCOUNT_NAMESPACE=wechat-main
CRM_CHECKPOINT=/Users/your-name/Library/Application Support/personal-crm/checkpoint.json
WECHAT_CONTACTS=visible_wechat_id_alice,visible_wechat_id_bob
WECHAT_SINCE=2026-06-06T00:00:00Z
```

`CHATLOG_SCOPES` 是权限 `0600` 的本地 JSON 数组，每项包含
`requested_id/person_name/account_id/conversation_id/conversation_type`。其中
`requested_id` 必须与 `WECHAT_CONTACTS` 完全一致；账号和内部会话 ID 只留在 Mac，
不会写入 Webhook。二进制应从已审计 Release 固定到私有目录，并配置 SHA-256。

先做不推进 checkpoint 的 dry run：

```bash
CRM_ENV_FILE=/absolute/path/connector.env uv run personal-crm-wechat --dry-run
```

确认输出只包含摘要后，再去掉 `--dry-run`。常驻模式使用
`personal-crm-wechat --watch`。Connector 按一天窗口回填并保留五分钟重叠；只有 NAS
对整个批次（包括空窗口）返回成功且无错误项时，才会原子推进 checkpoint。
chatlog 读取失败、NAS 5xx 或进程重启均不会丢失水位。

多客户端同步时，每台 Mac 的 `CRM_CLIENT_ID` 必须不同，本地 checkpoint 也独立保存。
同一微信账号使用相同的 `CRM_ACCOUNT_NAMESPACE`，不同微信账号使用不同值；多账号映射
可在每条 scope 中配置 `account_namespace`。该命名空间和内部会话 ID 只用于本机计算
SHA-256，不直接出站。稳定消息键取自账号、会话及微信 `server_id`，不包含设备 rowid。
缺少 `server_id` 的消息继续按旧事件键去重，不按时间或正文猜测身份。

旧客户端仍可上报；服务端将未标识客户端的请求记为 `legacy`。升级后首次回放旧事件
会补齐稳定消息键，不重建原记录。历史记录必须先由原设备回放补齐身份，另一设备才能
对这些旧记录跨机去重；只凭旧键无法恢复原先未上报的服务器消息 ID。

管理员可携带 `X-Webhook-Token` 查询内网端点
`GET /api/v1/webhooks/wechat/clients`，核验每台设备的 `synced_through`、最近成功时间和
接收/重复计数。状态查询与同步使用相同鉴权，不返回联系人或聊天内容。

Connector 在解析 `record` 时只在当前调用栈内使用原始 `content`，随后立即丢弃，
不在日志、checkpoint 或 Webhook 中保存正文。`WECHAT_FACT_EXTRACTION=true` 会启用
高置信规则抽取器：仅处理对方明确自述的偏好、边界、人生事件、组织和联系方式，
并只外发受限结构化 Fact；出站消息、卡片、链接和超长内容不抽取。抽取器通过独立
Protocol 隔离，后续可替换成本地模型或 Agent，同时保持原文不离开 Mac 的边界。
启用时还会为每个实际出现消息的白名单会话生成一个可幂等去重的 `contact` Fact，
用于记录微信来源身份并验证 Fact 链路；它不包含内部账号或会话 ID。
