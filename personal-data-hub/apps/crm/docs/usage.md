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

## Codex Skylight 与 Memos 日报查询和事件

两个新增查询工具均支持省略 `day`，默认查询北京时间今天：

```json
{"name":"get_daily_codex_skylight","arguments":{}}
```

```json
{"name":"get_daily_memos_report","arguments":{}}
```

```json
{"name":"get_daily_memos_report","arguments":{"day":"2026-10-03"}}
```

日期参数必须是 `YYYY-MM-DD`。`timezone` 默认为 `Asia/Shanghai`；Skylight 按源文件
UTC 开始时间转换后归属业务日期，Memos 按日报首行 `#日报 YYYY-MM-DD`（兼容
`# 日报 YYYY-MM-DD`）归属日期。Memos 只读配置作者的 `NORMAL` 日报，排除归档和其他 Memo。

Skylight 的源目录实际名为 Skysight。`summary_type` 支持 `preferred`（默认，优先 6h，
10min 补空档）、`all`、`6h`、`10min`。查询返回同步摘要文件的完整 Markdown 正文，
不重新生成摘要。分页参数 `offset=0, limit=20`，`next_offset` 非空时继续下一页。
正文首段最长 4000 字符；`next_content_offset` 非空时按 `content_read_tool` 和
`content_read_arguments` 调用 `get_daily_review_content`，直到 `next_offset=null`。
续读使用结果返回的明确日期，避免跨午夜跳到另一业务日。普通查询读取当前源文件，
可能随上游修订变化；事件查询读取冻结快照。

生产启用两个每天北京时间 23:00 的独立事件：

- `crm.daily_codex_skylight.ready`
- `crm.daily_memos_report.ready`

在已认证的 `/mcp` 请求中调用 `events/list` 查看事件，再用 `events/subscribe` 订阅。
事件参数是空对象，订阅需要支持 MCP Events 的客户端及公网 HTTPS Webhook：

```json
{
  "name": "crm.daily_memos_report.ready",
  "arguments": {},
  "delivery": {
    "mode": "webhook",
    "url": "https://your-callback.example.com/events",
    "secret": "whsec_<base64-encoded-24-to-64-byte-secret>"
  }
}
```

这是 `events/subscribe` 的参数示例；MCP 请求信封由客户端按协商的协议版本构造。
回调需处理验证 challenge，并校验基座发送的签名。未订阅时不会收到定时 Webhook。
事件仅含日期、数量、是否空日和 `read_tool` / `read_arguments`，据此调用
`get_daily_review_event_report` 获取正文；长正文使用 `get_daily_review_event_content`。
事件及快照仅其配置的 OAuth 所有者可访问。当天没有日报时返回 `empty_day=true`，
不改读昨天；晚于 23:00 的新文件或日报修改可用普通日期查询获取，不自动修订已推送快照。
源不可用时保留待生产日期，恢复后补发；投递失败由现有持久化事件队列重试。
