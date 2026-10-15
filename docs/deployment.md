# 独立部署

运行一个 `personal-crm-server` 进程，使用 PostgreSQL 或 SQLite 和一个附件目录。没有 Hub、消息队列、定时报告或额外业务数据库依赖。

## 服务配置

从 `.env.example` 开始。生产使用 PostgreSQL 时，将 `DATABASE_URL` 指向既有数据库，并设置持久的 `CRM_ASSET_ROOT`。先备份，再执行 `personal-crm migrate`，最后启动服务。启动过程不自动迁移数据库。

- HTTP 读写：`CRM_API_TOKEN`；只读：`CRM_VIEWER_TOKEN`。读写令牌不会自动赋给只读调用方。
- 微信写入：`WECHAT_WEBHOOK_SECRET`，只用于私聊批量写入和媒体上传。
- 分段间隔：`WECHAT_INTERACTION_GAP_MINUTES=30`。修改只影响后续追加，不重组已有正文。
- 公网 MCP：`MCP_DEVELOPMENT_NO_AUTH=false`，设置公开 URL、OIDC discovery/client、授权用户名及 OAuth 签名和存储密钥。
- `OIDC_READ_ONLY_USERNAMES` 中的用户只读；`OIDC_AUTHORIZED_USERNAMES` 明确授权读写。沿用 `mcp-platform` 的 OAuth，未新建用户/角色系统。
- `OAUTH_STORAGE_PATH` 持久化，迁移部署时保留原目录、密钥和 `personal-crm-oauth-v1` 盐对应的状态格式。

反向代理转发整个服务，包含 `/mcp`、`/.well-known/*` 和 OAuth 路由。开发无认证模式只允许回环监听，不能用于公网。

独立服务的 HTTP 环境变量使用 `CRM_API_TOKEN` / `CRM_VIEWER_TOKEN`，不读取 Hub 配置文件；若从宿主切换，将原令牌值放入对应配置，原只读令牌仍只读。

## 数据库升级与备份

`personal-crm migrate` 创建当前 `crm_*` 结构。旧 001–003 revision 仅保留升级标记，新安装不创建旧人物、Fact 或 Reminder 表。已经升级至 `004_person_archive` 的数据库可直接使用。

已有旧 CRM 表需要转换时：备份数据库与附件，暂停原写入，执行 migrate，再执行一次 migrate-legacy。转换读取既有表；旧 Hub 附件引用存在时可以复用其文件，运行不需要 Hub Python 包。目标归档非空时拒绝重复转换。没有旧表时转换结果为零。旧数据不删除。

SQLite 备份：`uv run personal-crm backup /safe/path/crm.db`；PostgreSQL 使用已有 `pg_dump`。附件与 OAuth 目录单独备份。回退软件不覆盖切换后产生的新数据。

## 微信读取器与附件

微信读取器是 Mac 上已有的 `chatlog-keeper`，需提供 `directory --source wechat` 和 `message-stream-v1 --selection-stdin` 协议。先完成本机数据授权；本项目不安装读取器、不提取密钥或修改系统授权。

`connector.env.example` 是采集配置样例。`CRM_CLIENT_ID`、`CRM_ACCOUNT_NAMESPACE`、`CRM_CHECKPOINT` 和可选的 `CHATLOG_SCOPES` 沿用原值；来源身份不靠备注名匹配。只需要 `CRM_ENV_FILE` 指向实际文件即可运行采集 CLI，不依赖 Hub 客户端安装器。

只有需要保留能读取的媒体时才启用 `WECHAT_MEDIA_ENABLED=true`，并安装原媒体读取依赖：

```bash
uv pip install -r requirements-wechat-media.txt
```

媒体读取只复用已有数据库密钥缓存；保留可取得的原文件，不增加 OCR、转写或解密能力。文件暂时缺失时元数据和 attachment:// 引用仍保留，后续补文件不重写正文。
