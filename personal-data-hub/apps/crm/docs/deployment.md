# 部署说明

## NAS 公共基座部署

CRM 使用私有 `ump45nose/mcp-platform` 的版本依赖，`uv.lock` 锁定 SDK 的完整 Git 提交。生产配置集中在本仓库 `mcp.app.yaml`；NAS 目标配置、GitHub 凭据及业务秘密保存在仓库外。

已迁移的生产地址为 `https://crm-home.172906573.xyz/mcp`。业务进程由共享 Cloudflare Tunnel 直接访问 NAS 的 `192.168.31.201:18086`，不增加数据库或网关进程。原 NPM 配置保留作为迁移回退路径。

NAS 本机执行：

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl doctor --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan personal-crm --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy personal-crm --target nas
```

更新前提交业务修改，并检查 `plan`。构建步骤使用宿主机 GitHub 凭据获取锁定版本，生成 wheel 后注入镜像；镜像和构建上下文不包含凭据、生产 env 或数据。旧 `Dockerfile`、`compose.yml` 与 Nginx 样例保留用于历史部署参考，生产更新以公共基座 CLI 为准，不再直接运行旧目录的 `docker compose build`。

部署保留 `personal-crm_crm-data`、`/data/oauth`、签名及加密密钥、`personal-crm-oauth-v1` 盐。Authelia 客户端 `personal-crm`、原 discovery/issuer、`28443` 授权与 token 端点以及 `/auth/callback` 不变。共享 Tunnel 的其他路由不变；ddns-go 只停止管理 CRM 的 A/AAAA 记录。

业务生命周期、Webhook 和提醒任务仍在 CRM 内运行。新增公共限流、超时和输出限制在本次迁移关闭，以保留原调用行为和成功返回结构。

## 接入与冒烟检查

```bash
curl -fsS https://crm-home.172906573.xyz/healthz
/home/yuwk/mcp-platform/.venv/bin/mcpctl package personal-crm --target nas
```

未登录 MCP 请求应返回 401 和资源发现地址。授权用户可读取；只读用户不能写入。业务读写只在隔离数据库验证，生产只读。新连接首次登录需同意授权；已有 GPT/dots 连接继续使用原 App 和插件身份。插件包生成不代表客户端已发布，用户界面验收需分别确认。

## 备份与代码回滚

每次更新在 `/vol2/1000/Docker/stacks/mcp-platform/runtime/personal-crm/releases/` 保存私有变更记录、SQLite 在线备份和 OAuth 状态备份。备份文件权限为 600，发布目录为 700。

手工备份使用当前镜像的管理命令：

```bash
sudo -n docker exec personal-crm-crm-1 personal-crm backup /data/backups/crm.db
sudo -n docker exec personal-crm-crm-1 personal-crm integrity
```

代码与本次入口配置回滚：

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl rollback personal-crm --target nas
```

回滚恢复原镜像、共享配置和 DNS，不恢复旧数据库或 OAuth 快照。共享配置或 DNS 出现外部修改时停止覆盖并记录 `needs_attention`。首次迁移回退会恢复 NPM 对应 DNS 和原 DDNS 列表；后续回退恢复上一个基座版本。

数据恢复需单独安排停止写入并保留当前库副本，再恢复备份和检查完整性。数据库、OAuth 状态及备份含私人资料，应按原备份策略保护。单实例更新允许短暂重启和流连接重建。

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

## Skysight 摘要

只读工具 `get_daily_codex_skylight` 读取已同步摘要，默认按 Asia/Shanghai 今天查询。preferred 优先 6h，用 10min 补空档，完整正文可通过 `get_daily_review_content` 续读，source 仅支持 `codex_skylight`。

日报事件可显式启用 `crm.daily_codex_skylight.ready`，沿用已有身份和冻结快照读取；统一 Hub 当前关闭该独立事件，保留聊天事件。Memos 日报查询、源配置和事件生产已移除。旧快照文件及订阅状态保留，不重新生产旧事件。

统一 Hub 入口及本次来源变化见仓库根 README 和 `docs/plans/2026-10-15-source-cleanup.md`。Mac 调整清单在 `docs/client-requirements/source-cleanup.md`。
