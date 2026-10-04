# personal-crm

面向个人 Agent 的模块化个人 CRM。NAS 保存唯一 SQLite 数据源并提供 Webhook 与 MCP；Mac Connector 通过本机 `chatlog-keeper message-stream-v1` 只读微信数据库，仅向 NAS 推送无正文互动摘要和本机定位引用。系统不自动发微信，也不包含 RPA、自动回复或代发能力。

## 架构

代码采用模块化单体，部署为两个进程：

- NAS：`core`、`storage`、`reminders`、`metrics`、`webhook`、`mcp`、`app`。
- Mac：`connector`，以子进程 stdin/stdout 调用本地只读导出器，并通过 HTTPS 主动出站。

核心数据严格为四张表：`people`、`interactions`、`facts`、`reminders`。所有实体 ID 使用 UUIDv7，时间统一为 UTC，SQLite JSON 字段带 `json_valid()` 约束。

多台 Mac 可同时运行 Connector：每台设备使用独立 `CRM_CLIENT_ID` 和本地 checkpoint，
服务端以 `source_message_key` 对同账号的服务器消息跨设备去重。`sync_clients` 是独立的
技术状态表，只记录设备成功水位和计数，四张业务表保持原有职责。

## 快速开始

需要 Python 3.12 与 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra dev
cp .env.example .env
uv run alembic upgrade head
uv run personal-crm-server
```

本地未配置 OAuth 时，可直接用 MCP 客户端连接 `http://127.0.0.1:8080/mcp` 验证十四个工具。管理 CLI：

```bash
uv run personal-crm integrity
uv run personal-crm backup /safe/path/personal-crm.db
```

## 对外端点

- `POST /mcp`：Streamable HTTP MCP。
- `GET /.well-known/oauth-protected-resource`：兼容发现入口，跳转到权威的 `/mcp` 后缀元数据（启用 OAuth 后）。
- `GET /healthz`：进程与 SQLite 完整性检查。
- `POST /api/v1/webhooks/wechat`：Mac Connector 批量导入。

## 当前交付状态

- P0：四表、迁移、Repository、事务、备份恢复和领域测试已实现。
- P1：十四个 MCP 工具、本地 `initialize` 与工具调用已实现。
- P2：每周三条上限、重要日期优先、cadence、自动完成和周绩效已实现。
- P3：Authelia OIDCProxy 与用户名白名单代码、反代样例已实现；各客户端实机鉴权需分别验收。
- P4：Webhook 共享密钥、严格输入、幂等事务及合成数据测试已实现。
- P5：五人白名单映射、真实微信 4.1.11 消息流、隐私裁剪、稳定批次和失败重试已实机验证；launchd 常驻与完整 90 天回填仍需持续验收。
- P6：两周样品期尚未开始，必须在真实使用后再决定扩展数据模型。

代码测试、Docker 部署、健康检查、MCP 鉴权调用、微信真实导入、Reminder 实际触发和用户使用验收是独立状态，不能互相替代。

## 安全与权限

公网模式使用与 SmartSearch 相同的 FastMCP `OIDCProxy` 对接 Authelia。上游申请 `openid profile offline_access`，并从 `preferred_username` 映射 CRM 权限：`OIDC_AUTHORIZED_USERNAMES` 可读写，列入 `OIDC_READ_ONLY_USERNAMES` 的账号只读。动态 MCP 客户端仍由 OIDCProxy 管理，Authelia 只需登记固定的 `personal-crm` 客户端。

只向反代暴露 `/mcp`、OAuth 路由、`/healthz` 和精确的微信 Webhook 路径。所有秘密仅从环境变量或密钥管理注入；数据库和日志不得出现完整微信正文。

使用和部署细节见 [`docs/usage.md`](docs/usage.md) 与 [`docs/deployment.md`](docs/deployment.md)。

## 插件展示与场景说明

本仓库同时维护 **Personal CRM** 的名称、场景描述和图标。插件包位于仓库根目录，接入和维护说明见 [插件说明](docs/plugin.md)，图标来源见 [图标来源](assets/plugin/SOURCES.md)。


## MCP 公共基座部署

本服务使用私有仓库 `ump45nose/mcp-platform` 的版本依赖。业务工具、Webhook、提醒及数据库继续由 CRM 维护，认证、权限和 HTTP 装配由公共基座提供。

`mcp.app.yaml` 是生产入口、认证引用、持久化卷和插件身份的唯一清单。SDK Git 来源使用 `v0.1.0`，`uv.lock` 锁定提交；普通更新不清空 `/data/oauth`，不轮换签名或加密密钥。

NAS 更新使用以下命令（需管理员权限读取现有 env 和共享配置）：

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan personal-crm --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy personal-crm --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl rollback personal-crm --target nas
/home/yuwk/mcp-platform/.venv/bin/mcpctl package personal-crm --target nas
```

部署要求仓库没有未提交修改。构建在宿主机获取私有依赖并生成 wheel，镜像不包含 GitHub 凭据、env 或生产数据。发布记录、SQLite 在线备份和 OAuth 状态备份位于 `/vol2/1000/Docker/stacks/mcp-platform/runtime/personal-crm/releases/`，权限 600。

公网 MCP 地址仍为 `https://crm-home.172906573.xyz/mcp`，入口切换到共享 Cloudflare Tunnel 直达 CRM。原 NPM 配置保留用于回退；ddns-go 停止维护 CRM 的 A/AAAA 记录，其他域名不变。Authelia discovery、issuer 和 `28443` 授权／token 地址保持原样。

现有 `personal-crm_crm-data` 数据卷、`/data/oauth`、`personal-crm-oauth-v1` 加密盐、Authelia 客户端、App ID 与插件身份保持不变。代码回滚恢复镜像和本次配置，不恢复旧业务数据或 OAuth 快照。

首次接入需用户登录并同意授权；更新后通过原 GPT/dots 连接调用只读工具验证，无需重建 App。插件打包不自动发布或重新连接账号。

本地离线开发必须显式设置 `MCP_DEVELOPMENT_NO_AUTH=true` 并监听 `127.0.0.1`；生产凭据缺失时拒绝启动，不自动降级为匿名服务。

MCP 保留线上已有 `get_daily_chat_records`，支持按日期分页读取已同步微信聊天原文，不代发消息。公共基座的新增限流、超时及输出限制在本次 CRM 迁移中关闭，保留原成功返回结构。
