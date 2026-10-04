# 邮件 MCP 更新、迁移与网页接入记录

2026-10-05（Asia/Shanghai）。服务升级与 NAS／Tunnel 切换完成；GPT 网页表单正在接入，尚不能报告网页部署完成。

## 实际部署

| 项目 | 已部署值 |
|---|---|
| 上游业务包 | `mcp-email-server==1.11.0`，提交 `uv.lock`，未 fork 或修改上游 |
| 公共运行时 | `v0.1.0`，`34abcd4bd354f89681b1dc0bc1d27783c0a616ba` |
| 镜像源码提交 | `c3d3e0cee79e870c0386a6725d7168d027733ff5`，从隔离干净检出构建 |
| 镜像 | `local/email-mcp:c3d3e0cee79e-platform-34abcd4bd354` |
| 本地镜像 ID／内容摘要 | `sha256:5a767de4215b925cc6fc1ec24e96f46f71d829860249e02b4c4505dabc8016c0`（本地构建，未推送镜像仓库） |
| 新容器 | `mcp-platform-email-mcp-1`，健康，平台 Compose 的 `email-mcp` 服务 |
| 运行配置 | `1000:1001`、`/data`、init、`tool_net`、`127.0.0.1:9557`、原出口代理 |
| 公网入口 | `https://email-home.172906573.xyz/mcp` |
| Tunnel | 复用 `local-env-mcp-cloudflared`，保留其他四条共享业务路由与兜底 |
| OAuth | 公共运行时代理 Authelia，保留原 issuer／discovery 和 28443 授权端点；仅当前用户 |
| 切换记录 | 私有 runtime 下 `email-mcp/releases/20261004T163332284192/journal.json`，状态 complete |

完整构建输入摘要、运行配置、数据宿主路径和变更前快照仅保存在仓库外的私有发布记录；普通源码及插件展示资料不包含秘密、OAuth 状态、邮箱账号资料或附件。切换执行器使用后续已提交的部署修正，镜像实际构建提交仍以表格为准。

## 数据保留与验收

旧 `email-mcp` 容器已停止，旧 tool Compose 仅移除该服务，原 Dockerfile 与数据目录保留。停止共享数据库的管理进程后制作一致性 SQLite 副本，复制匹配的 bootstrap、附件和凭据；新版仅打开平台私有迁移副本，将 schema v3 升级为 v5。四个账号、原表字段和值及 bootstrap 摘要已验证保留。目录 700、秘密文件 600。`email-mcp-data` 与 `email-mcp-oauth` 为独立外部持久卷，没有新旧实例共用数据库。

| 验收层 | 结果 |
|---|---|
| 配置及基本冒烟 | 清单、Compose 候选通过；3 个受影响路径测试通过 |
| Tunnel／TLS | 公网健康响应通过，证书与原域名校验保持启用 |
| 未认证请求 | 本机及公网 MCP 返回 401；挑战指向实际 protected-resource 发现路径 |
| OAuth 发现 | 邮件入口发现通过，网页自动识别 authorize／token／register／resource |
| 同进程 MCP 桥接 | initialize／tools/list、19 个工具 schema 等价、结构化账号返回、只读／写权限分流通过 |
| 邮箱后端 | 4 账号发现与一次只读 INBOX 文件夹查询通过，不读取邮件正文，不触发发送／删除／移动 |
| GPT 网页 | 表单已填，CIMD 自动发现通过，256×256 Zoho PNG 被表单接受；尚待提交和首次用户授权 |

NAS 本地 DNS 曾命中旧通配 DDNS，公网验收使用公共 TCP DNS，并保留 HTTP Host、TLS SNI 与证书验证，不修改宿主 resolver 或关闭 TLS 校验。失败尝试已按本次配置和 DNS 回退，保留各次新版数据和 OAuth；最终切换通过。

## GPT 网页与身份

按用户后续明确要求，禁止使用 Plugin Creator，也不上传 ZIP 代替网页接入。通过用户提供的 Browser Relay 远程中继操作已有已登录页面，在个人目录核对无“邮件”既有连接后，从“添加 → 创建自定义 MCP 服务器”进入表单。连接名称“邮件”、描述和公网 MCP URL 来自唯一正式 `mcp.app.yaml`。

网页选择 OAuth，并自动发现 CIMD 客户端元数据模式、`openid profile offline_access`。不向网页提交 Authelia 客户端秘密。Zoho Mail 官方矢量图直接渲染为 256×256 透明 PNG，8999 字节，符合网页上传限制；图标须以真实页面截图验收。真实网页连接／App ID：尚未创建，不能以包版本或虚构 ID 代替。

首次登录、MFA、同意授权由用户在网页完成。授权前保持“待授权／待连接”；授权后再记录网页工具发现与一次客户端只读调用，不把本机后端验证当成网页工具调用结果。

## 更新与回滚

1. 后续更新只使用已提交、锁定的适配源码与 `uv.lock`，执行 `mcpctl plan email-mcp`、`mcpctl deploy email-mcp`。目标文件的 `source_roots.email-mcp` 与 `compose_files.email-mcp` 在仓库外；目标工作树应保持干净。
2. 首次切换失败由迁移脚本恢复旧容器对原目录的使用，并比较后恢复本次 Compose、Authelia、Tunnel、DDNS、DNS 和卷映射。发生外部修改时停止覆盖，保留需人工处理记录。
3. 正式投入使用后，禁止重新执行首次迁移、用 1.4.1 打开 v5 或自动恢复旧数据。代码／入口回滚仅恢复镜像与本次配置，使用兼容 v5 的版本恢复服务，保留当前 v5 数据、当前 OAuth 状态及新授权。
4. 不自动倒灌旧库。数据灾难恢复另行核对，不能通过代码回滚覆盖部署期间的新邮件设置或写入。旧目录仅作为受保护的迁移前证据保留。
