# 邮件 MCP

官方 `mcp-email-server==1.11.0` 的平台薄适配。公共运行时锁定 `v0.1.3`（提交 `c7ec37bb41629b3925b39abd22df707a16881dc9d245c`），上游业务代码不改写。四个邮箱的身份、收发设置和原策略保留；新增公网 Authelia OAuth。

入口：`https://email-home.172906573.xyz/mcp`。使用回环端口 9557，独立运行在 `mcp-platform` Compose 的 `email-mcp` 服务中，复用现有 `tool_net`。业务卷 `email-mcp-data` 与 OAuth 卷 `email-mcp-oauth` 分开保存，宿主路径及秘密在仓库外。

## 首次迁移

管理员在干净的完整提交上执行 `migrate_nas.py`，设置 `PYTHONPATH` 指向该检出的 `src`。脚本复用平台部署锁、镜像构建、共享配置校验及比较后更新；先验证升级副本，后停止旧容器，复制一致数据并在平台启动。旧 tool Compose 只移除邮件服务，原 Dockerfile 和原数据目录保留。脚本拒绝重复导入旧目录。

新版将 managed schema v3 升到 v5。先保留 SQLite 一致性副本和匹配的 bootstrap；原目录不会被新版本打开。旧版不能使用 v5，新旧实例不能共享一个目录。

## 后续更新与回滚

更新适配项目的锁文件，提交后运行 `mcpctl plan email-mcp`、`mcpctl deploy email-mcp`。目标配置的 `compose_files.email-mcp` 指向平台 Compose；更新只协调邮件服务，保留同一 Compose 的其他服务。

首次切换失败时脚本恢复旧容器及本次共享配置和 DNS；新版数据与 OAuth 不覆盖原目录。正式投入使用后禁止重新执行首次迁移或用 1.4.1 打开 v5。常规代码回滚使用兼容 v5 的镜像，保留当前业务数据和 OAuth 状态；数据恢复单独处理，不能自动倒灌旧库。

## 收件人策略

2026-10-09 已通过上游 CLI 将 managed 策略的 `allowed_recipients` 设置为 `["*"]`（策略修订 5 → 6），允许向所有有效邮件地址发送；同一策略也用于转发，以及草稿、保存邮件中的收件人、抄送和密送检查。四个既有邮箱均有发信能力，其他策略保持原值。策略保存在 `email-mcp-data` 业务卷中，每次调用读取当前值，无需重建镜像或重启服务。

检查当前修订后再更新，`*` 必须用引号避免 shell 展开：

```bash
docker exec mcp-platform-email-mcp-1 mcp-email-server config policy --json
docker exec mcp-platform-email-mcp-1 mcp-email-server config update-policy \
  --expected-revision <当前修订号> --allowed-recipients '*' --json
```

空收件人列表表示禁止所有收件人。后续收窄策略应使用当前修订和所需地址或 glob 模式调用同一 CLI；只更新收件人字段，不恢复整个数据库。此次变更前后策略和验证结果保存在仓库外的私有 runtime `email-mcp/policy-changes/` 下，身份、密钥、业务数据和 OAuth 状态沿用现有配置。

## GPT Web

在已登录的 ChatGPT 网页 Plugins 页面，使用“添加 → 创建自定义 MCP 服务器”，填写正式清单中的展示名称“邮件”、描述、`https://email-home.172906573.xyz/mcp`，身份验证选择 OAuth。禁止使用 Plugin Creator，不能用 ZIP 保存结果代替网页注册。没有复用其他 App，也不生成占位身份。

网页自动发现邮件入口的 OAuth 设置，支持 CIMD 和 DCR。CIMD 由 ChatGPT 提供客户端元数据，无需把 Authelia 客户端密钥填入网页。首次 Authelia 登录、MFA 和授权由用户在网页完成。网页连接成功后再记录真实连接／App ID；展示清单里的包版本不代表网页发布版本。

图标复用 [Zoho Mail 官方资源](https://www.zohowebstatic.com/sites/zweb/images/productlogos/mail.svg)，来源见 `assets/SOURCE.md`。从原始矢量图渲染 256×256 透明 PNG（8999 字节），满足网页 PNG／10 KB 限制，保持原配色和形状。

验收仅检查协议、工具枚举、账号发现及只读邮箱查询，不发送、删除或移动邮件。Tunnel、协议、邮箱后端和客户端连接分别记录状态。当前部署及网页接入进度见 [部署记录](../../docs/email-mcp-rollout-2026-10-05.md)。

已通过网页表单完成注册与用户 OAuth，账户显示已连接，Zoho 图标及 19 个工具已在真实页面验收。[打开“邮件”](https://chatgpt.com/plugins/plugin_asdk_app_6ac285e95d74819193f153ce16dc5640)。真实 App ID 与网页连接状态见 [网页注册记录](../../docs/email-mmp-web-registration-2026-10-05.json)；网页表单身份没有插件 App 绑定，清单不声明占位 App ID，后续保留该连接身份。

GPT Web 只读验收通过：账号发现与 INBOX 文件夹查询各一次，返回 4 个账号、1 个文件夹；服务端审计均为 ok。未发送、保存草稿、删除、移动或修改邮件。
