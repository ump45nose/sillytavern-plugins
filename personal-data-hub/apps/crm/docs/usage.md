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
CHATLOG_SCOPE_MODE=all
CHATLOG_PAGE_SIZE=200
CHATLOG_WINDOW_SECONDS=86400
CHATLOG_OVERLAP_SECONDS=300
WECHAT_FACT_EXTRACTION=false
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

`CHATLOG_SCOPE_MODE=all` 是默认模式，动态枚举本机微信的全部单聊和群聊；
`all_direct` 只读取全部单聊，`configured` 才使用 `WECHAT_CONTACTS` 白名单。
`CHATLOG_SCOPES` 保留原有联系人的身份映射，新会话沿用源目录身份，不按同名昵称合并。
源协议每次最多读取 128 个会话；连接器分批读完后才提交本轮数据。
二进制仍固定到已审计 Release，并验证 SHA-256；不提取或生成新密钥。

```bash
CRM_ENV_FILE=/absolute/path/connector.env uv run personal-crm-wechat --dry-run
CRM_ENV_FILE=/absolute/path/connector.env uv run personal-crm-wechat --watch
```

命令和常驻日志只输出数量、接收状态和错误类别，不输出聊天正文。
正文、消息类型、时间、发送方和源消息的其他字段原样保存在 `Interaction.message` JSON，
不生成摘要、不启用 Fact、ASR 或模型处理。图片、语音、文件等保留源读取器返回的
内容和元数据；源端只返回占位文本时，不代表附件文件已经下载。
`summary` 的 `消息内容：` 前缀用于原有查询兼容；NUL 字符只从兼容 Text 字段中移除，
完整 JSON 与每日记录详情仍保留原字符、空白和长正文。

常驻模式沿用一天窗口及五分钟重叠。每个 Webhook 分片不超过 500 条互动/事实；
只有最后一片成功才推进 NAS 成功水位，整轮确认后才原子保存 Mac checkpoint。
中间失败时可幂等重放已经接收的分片。历史追赶快速继续，追平后按配置周期轮询。
历史回填应先停止原 Agent，备份配置和 checkpoint，再使用独立空 checkpoint 重读
所需窗口；重复消息补齐原记录的源消息，不重建互动 ID。不能只倒退时间却保留
已确认消息键，否则本机去重会跳过需要补齐正文的旧消息。

多设备保持独立 `CRM_CLIENT_ID` 和 checkpoint；同账号使用相同
`CRM_ACCOUNT_NAMESPACE`。稳定身份仍由账号、会话及服务器消息 ID 生成，
设备 rowid/offset 不参与跨机身份；缺少服务器 ID 时只按设备事件键去重。
已归档源消息不会因另一设备的本地 offset 不同而反复覆盖。
旧客户端没有 `message` 字段时仍兼容。显式删除墓碑继续阻止历史重放复活。

管理员使用原 `X-Webhook-Token` 查询
`GET /api/v1/webhooks/wechat/clients`，检查设备水位、最近接收时间及计数。
部署前执行 `apps/crm` 的 Alembic `upgrade head`；已有统一 PostgreSQL 没有
Alembic 版本表时，先备份，再执行 `database/003_wechat_messages.sql` 中的
可空 `message JSON` 加列语句，不回放初始建表迁移。

## Skysight 摘要

只读工具 `get_daily_codex_skylight` 读取已同步摘要，默认按 Asia/Shanghai 今天查询。preferred 优先 6h，用 10min 补空档，完整正文可通过 `get_daily_review_content` 续读，source 仅支持 `codex_skylight`。

日报事件可显式启用 `crm.daily_codex_skylight.ready`，沿用已有身份和冻结快照读取；统一 Hub 当前关闭该独立事件，保留聊天事件。Memos 日报查询、源配置和事件生产已移除。旧快照文件及订阅状态保留，不重新生产旧事件。

统一 Hub 入口及本次来源变化见仓库根 README 和 `docs/plans/2026-10-15-source-cleanup.md`。Mac 调整清单在 `docs/client-requirements/source-cleanup.md`。
