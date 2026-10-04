# CRM 首次迁移验收记录

日期：2026-10-04。只执行首版关键路径冒烟；未运行完整 CRM 回归。

## 部署版本与入口

- 公共运行时：`v0.1.0`，提交 `34abcd4bd354f89681b1dc0bc1d27783c0a616ba`。
- CRM 生产提交：`3e9bb03933c89820501135f81a8102bc23377dbe`。
- 生产镜像：`local/personal-crm:3e9bb03933c8-platform-34abcd4bd354`。
- Python 3.12，FastMCP 3.4.4、MCP SDK 1.28.1、Authlib 1.7.2。
- 公网入口：`https://crm-home.172906573.xyz/mcp`，共享 Tunnel 直达业务进程。
- 完成记录：`/vol2/1000/Docker/stacks/mcp-platform/runtime/personal-crm/releases/20261004T092000353368/journal.json`。

保留原数据卷、`/data/oauth`、签名及存储密钥、`personal-crm-oauth-v1` 盐、Authelia 客户端、App 和插件身份。CRM issuer 的末尾 `/`、资源 URL、回调均未改变。Authelia 原 discovery、issuer、`28443` 授权/token 地址与既有客户端不变，未重启 Authelia。

## 已验证

| 项目 | 结果 |
|---|---|
| 公共运行时 HTTP、生命周期、工具调用与安全启动约束 | 通过 |
| 生成项目真实启动、健康检查和 HTTP MCP initialize | 通过 |
| 未认证生产请求 | 401，包含资源发现挑战 |
| 授权读取、只读拒绝写入、执行权限默认拒绝 | 隔离身份配置通过 |
| CRM 读写和成功返回结构 | 内存 SQLite 建档与搜索通过，生产未写入业务测试数据 |
| OAuth 持久化 | FileTree、DiskStore 重启读取通过；原 53 条加密记录可按旧盐解密 |
| URL client_id / CIMD | 存储与元数据通过；原 OpenAI 连接保持可用 |
| DCR / PKCE | 临时注册通过，缺少 PKCE 被拒绝，S256 进入授权流程；临时客户端已删除 |
| 既有 OpenAI CRM 连接 | 迁移前后查询不存在的测试姓名均成功返回空列表，未重新授权 |
| token 端点 | 迁移后既有连接使用期间观察到 POST /token 200 |
| 原远程网关 | 本机健康检查 200，现有 NAS MCP 连接目录读取成功，原 Tunnel 路由保留 |
| 失败回滚 | 隔离模拟 DNS 失败后恢复共享文件并记录 complete；首次真实部署在备份步骤失败时未更新原服务 |
| 重复部署 | 相同版本和配置验证通过，未重建或重启业务容器 |
| 官方候选校验 | 新 Authelia 客户端副本与 Tunnel 副本通过官方校验，未改写生效配置 |
| 外部修改保护 | 候选生成后修改、回滚前修改均拒绝覆盖 |
| 插件包 | 原 App 绑定保留，仅元数据、图标、连接地址及中文接入说明 |

公共包首轮四项冒烟通过；部署保护修正后只重跑两项受影响冒烟。CRM 四项选定冒烟通过，另修正一处测试参数后只运行该项。未扩大到业务回归。

## 运维交接与待确认项

NAS 目标与秘密保存在 `~/.config/mcp-platform/`，未进入 Git 仓库或镜像。候选校验和外部修改保护的部署工具修正发布为 `v0.1.1`；生产运行时继续锁定 `v0.1.0`。基座应用目录登记实际生产提交，后续文档修改不触发生产重建。

原 NPM 配置保留。DDNS 仅移除 CRM 管理条目，其他域名与共享 Tunnel 路由不变。回滚恢复代码及本次入口配置，不恢复旧业务数据或 OAuth 快照。

现有 OpenAI 连接已验证；GPT 网页和 dots 界面内的用户交互验收尚未操作。首次用户登录／同意授权、插件客户端发布仍由客户端完成。token 200 和原连接可用不等同于完成所有客户端的完整登录与刷新场景。

插件包位于 CRM 工作副本 `dist/personal-crm-plugin.zip`。更新使用 README 中的 `mcpctl plan/deploy`，不要在旧 NAS 目录直接重建旧镜像。
