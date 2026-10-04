# 邮件 MCP

官方 `mcp-email-server==1.11.0` 的平台薄适配。公共运行时锁定 `v0.1.0`（提交 `34abcd4bd354f89681b1dc0bc1d27783c0a616ba`），上游业务代码不改写。四个邮箱的身份、收发设置和原策略保留；新增公网 Authelia OAuth。

入口：`https://email-home.172906573.xyz/mcp`。使用回环端口 9557，独立运行在 `mcp-platform` Compose 的 `email-mcp` 服务中，复用现有 `tool_net`。业务卷 `email-mcp-data` 与 OAuth 卷 `email-mcp-oauth` 分开保存，宿主路径及秘密在仓库外。

## 首次迁移

管理员在干净的完整提交上执行 `migrate_nas.py`，设置 `PYTHONPATH` 指向该检出的 `src`。脚本复用平台部署锁、镜像构建、共享配置校验及比较后更新；先验证升级副本，后停止旧容器，复制一致数据并在平台启动。旧 tool Compose 只移除邮件服务，原 Dockerfile 和原数据目录保留。脚本拒绝重复导入旧目录。

新版将 managed schema v3 升到 v5。先保留 SQLite 一致性副本和匹配的 bootstrap；原目录不会被新版本打开。旧版不能使用 v5，新旧实例不能共享一个目录。

## 后续更新与回滚

更新适配项目的锁文件，提交后运行 `mcpctl plan email-mcp`、`mcpctl deploy email-mcp`。目标配置的 `compose_files.email-mcp` 指向平台 Compose；更新只协调邮件服务，保留同一 Compose 的其他服务。

首次切换失败时脚本恢复旧容器及本次共享配置和 DNS；新版数据与 OAuth 不覆盖原目录。正式投入使用后禁止重新执行首次迁移或用 1.4.1 打开 v5。常规代码回滚使用兼容 v5 的镜像，保留当前业务数据和 OAuth 状态；数据恢复单独处理，不能自动倒灌旧库。

## GPT Web

在已登录的 ChatGPT 网页 Plugins 页面，使用“添加 → 创建自定义 MCP 服务器”，填写正式清单中的展示名称“邮件”、描述、`https://email-home.172906573.xyz/mcp`，身份验证选择 OAuth。禁止使用 Plugin Creator，不能用 ZIP 保存结果代替网页注册。没有复用其他 App，也不生成占位身份。

网页自动发现邮件入口的 OAuth 设置，支持 CIMD 和 DCR。CIMD 由 ChatGPT 提供客户端元数据，无需把 Authelia 客户端密钥填入网页。首次 Authelia 登录、MFA 和授权由用户在网页完成。网页连接成功后再记录真实连接／App ID；展示清单里的包版本不代表网页发布版本。

图标复用 [Zoho Mail 官方资源](https://www.zohowebstatic.com/sites/zweb/images/productlogos/mail.svg)，来源见 `assets/SOURCE.md`。从原始矢量图渲染 256×256 透明 PNG（8999 字节），满足网页 PNG／10 KB 限制，保持原配色和形状。

验收仅检查协议、工具枚举、账号发现及只读邮箱查询，不发送、删除或移动邮件。Tunnel、协议、邮箱后端和客户端连接分别记录状态。当前部署及网页接入进度见 [部署记录](../../docs/email-mcp-rollout-2026-10-05.md)。
