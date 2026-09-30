# 部署说明

## NAS Docker

从 `.env.example` 创建仅管理员可读的 `.env`。在 Authelia 中为 CRM 创建独立 OIDC client，callback URL 配为：

```text
https://crm.example.com/auth/callback
```

`PUBLIC_BASE_URL` 必须与公网源完全一致。OIDC client 使用授权码、刷新令牌、PKCE S256 和 `client_secret_basic`；scope 为 `openid profile offline_access`，claims policy 必须签发 `preferred_username`。为 `WECHAT_WEBHOOK_SECRET`、`OAUTH_JWT_SIGNING_KEY` 和 `OAUTH_STORAGE_ENCRYPTION_KEY` 分别生成随机长密钥，且不要复用 OIDC client secret。

`CRM_BIND_ADDRESS` 和 `CRM_HOST_PORT` 只控制宿主机端口映射；应用容器内仍监听 `PORT=8080`。仅供同机 Hermes 使用时保持绑定 `127.0.0.1`，需要接入容器化反向代理时再绑定 NAS 内网地址并配置防火墙。

首次启动与升级：

```bash
docker compose build
docker compose run --rm crm uv run --no-dev alembic upgrade head
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

HTTPS 反代参考 `deploy/nginx/personal-crm.conf.example`。MCP 流式端点必须关闭代理缓冲并保留较长读取超时；OAuth 还需要转发 `/.well-known/`、`/auth/`、`/authorize`、`/token`、`/register` 和 `/consent`。

部署后的独立验收顺序：

1. 未登录请求 `/mcp` 返回 401，资源发现文档可访问。
2. 白名单用户完成 Authelia 登录，非白名单用户无法调用工具。
3. 只读用户能查询，但修改工具被拒绝。
4. Hermes、Codex、Claude 分别完成 `initialize → tools/list → tools/call`。

任一客户端未通过时，不声明公网通用 MCP 已完成。

## 备份与恢复

备份使用应用提供的 SQLite 一致性备份入口，避免直接复制仍在 WAL 写入中的数据库：

```bash
docker compose exec crm uv run --no-dev personal-crm backup /data/backups/crm.db
docker compose exec crm uv run --no-dev personal-crm integrity
```

恢复前停止写入，保留当前库副本，再替换数据库文件。恢复后执行完整性检查，并回放人物、互动、Fact、Reminder 核心查询和一个重复 Webhook 批次。数据库和备份都含敏感资料，应加密保存。

## Mac launchd

先按 `docs/usage.md` 创建独立 `connector.env`，并将固定校验的导出器、白名单映射和可选 checkpoint 放入 `~/Library/Application Support/personal-crm`。推荐使用安装脚本，它会按当前用户生成绝对路径，并覆盖从另一台 Mac 迁移来的旧路径：

```bash
./deploy/launchd/install-macos.sh
```

安装脚本优先使用显式 `CRM_CLIENT_ID`，否则在
`~/Library/Application Support/personal-crm/client-id` 生成并持久化设备 UUID。
可用 `CHATLOG_EXECUTABLE=/absolute/path/to/audited-binary ./deploy/launchd/install-macos.sh`
选择已有固定校验的导出器；二进制不随配置迁移替换。

服务端首次升级多客户端版本前先备份数据库，再执行 `alembic upgrade head`。
迁移 `002_sync_clients` 为互动增加可空稳定消息键及唯一索引，并创建技术状态表；
等价 SQL 保存在 `database/002_sync_clients.sql`。客户端去重查询在 SQLite
`BEGIN IMMEDIATE` 写事务中执行，多个设备并发提交时不会竞争创建人物或事实。

也可手动复制并修改 plist：

```bash
cp deploy/launchd/com.personal-crm.wechat.plist.example \
  ~/Library/LaunchAgents/com.personal-crm.wechat.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.personal-crm.wechat.plist
launchctl kickstart -k "gui/$(id -u)/com.personal-crm.wechat"
```

卸载只移除服务注册，不删除 checkpoint：

```bash
launchctl bootout "gui/$(id -u)/com.personal-crm.wechat"
```
