# Tunnel 接入与 SmartSearch 退役记录

日期：2026-10-04。本轮范围为公网入口、应用登记和构建约定，GPT Web App／插件另行处理。

## 实际运行

| 服务 | 公网 MCP | 业务进程与认证 | 入口清单 |
|---|---|---|---|
| CRM | `https://crm-home.172906573.xyz/mcp` | 原 Compose／公共 SDK／Authelia | CRM 仓库根目录 |
| 钉钉 | `https://mcphub-home.172906573.xyz/mcp` | 原 MCPHub／北向 OAuth | dingtalk-workspace-plugin 仓库根目录 |
| 远程服务器 | `https://local-env-home.172906573.xyz/mcp` | 原 systemd 网关与独立执行器／Authelia | 本项目 integrations/local-env-mcp |
| Media Download | `https://media-download-home.172906573.xyz/mcp` | 业务 Compose 独立容器／SDK 2.3.0／文件 Bearer | media-automation/apps/media-download-mcp |

钉钉复用 `/opt/mcphub/data` 和全部原官方服务，未重启 MCPHub。远程服务器原 Tunnel 路由保留，未替换网关代码、执行器、常驻会话、issuer 或认证状态。CRM 运行时仍锁定 `v0.1.0`，本轮未部署新 CRM 镜像。

Media 接入期间曾使用 Python 3.12.13 的独立虚拟环境和锁定 wheel。并行业务部署随后切换为根 Compose 的 `media-automation-media-download-mcp-1`，仅发布回环地址 8091，镜像 `local/media-download-mcp:0.1.1-tunnel`，digest `sha256:673575b139acac3d2e0673df0a38618c24da3c5c9bee64e62a995d21b5bd5155`。临时 systemd 单元已停用，保留单一业务进程。

镜像站对 Python 3.11 返回 401，后续 Docker 构建器卡住并超时；未修改 Docker 全局配置，已撤下本次构建临时容器，当时使用相同受保护源码快照构建原生 wheel。最终采用业务部署的现有容器，未回退其并行开发改动。源码输入 SHA256、wheel 摘要与运行版本记录在 NAS 私有目录，不在仓库中保存秘密或运行数据。

Media 的业务源码仍处于原仓库的未提交开发中，本次只提交入口清单、部署文件与文档。应用目录版本对应这些部署配置；NAS 运行代码来自记录摘要的私有快照，不宣称功能源码已完整发布。

## 验收与变更记录

- 钉钉：本机与公网健康 200、匿名 MCP 401、OAuth resource/issuer 一致；DNS 切换共享 Tunnel CNAME，DDNS 停止管理原域名。
- 远程服务器：原公网健康、匿名拒绝和 OAuth 发现通过，现有路由未改变。
- Media：本机与公网匿名 401、带独立令牌的 initialize 和三个工具枚举通过；未调用下载工具或触发真实下载。
- Media 重复部署返回 unchanged，未更新业务、认证或 Tunnel，随后业务部署切换为容器，本轮适配实际运行状态并再次验证入口；不把该业务切换当作入口部署重启。CRM 公网健康与资源发现继续通过，远程服务器现有 NAS MCP 连接目录读取成功。
- 新入口模式的隔离失败冒烟通过：模拟 DNS 失败恢复 Tunnel 文件，业务及 Authelia 控制操作被禁止；原清单初始化冒烟通过。只运行这两项必要验证，未扩大业务回归。
- Media 首次公网验收因新域名解析仍命中旧通配 DDNS，收到路由器证书，工具保持 TLS 校验并回滚本次配置／DNS。增加最多五分钟的 DNS/TLS 就绪等待后再次部署成功；未向不可信证书的地址发送 MCP 令牌。

完成记录（NAS 私有文件，600 权限）：

- 钉钉：`/vol2/1000/Docker/stacks/mcp-platform/runtime/dingtalk/releases/20261004T133107661106/journal.json`。
- 远程服务器：`/vol2/1000/Docker/stacks/mcp-platform/runtime/local-env-mcp/releases/20261004T133553426622/journal.json`。
- Media：`/vol2/1000/Docker/stacks/mcp-platform/runtime/media-download-mcp/releases/20261004T140456583526/journal.json`。

## SmartSearch 退役

NAS `smartsearch-mcp` 容器、专用 NPM 入口、目标 DNS 地址记录、DDNS 管理项和 Authelia `smartsearch-mcp` 客户端已移除；NAS 原代码／数据目录及 Mac 原代码目录已移入私有回退备份。GitHub `ump45nose/smartsearch-mcp` 已归档。

保留仍被 CRM／远程网关使用的 `smartsearch_yuwk` 和 `smartsearch_identity` 策略，Authelia 其他客户端、模板及密钥不变。未删除独立上游 smart-search CLI，未操作 GPT Web App 或插件。

NAS 回退记录：`/vol2/1000/Docker/stacks/mcp-platform/runtime/retired/smartsearch-mcp-20261004T134053/journal.json`。Mac 回退目录：`/Users/yuwk/.local/share/mcp-platform/retired/smartsearch-mcp-20261004T134554`。备份限制在私有目录，不将完整 NPM 数据库备份作为日常恢复手段；回退需比较现有配置，仅恢复本次目标行和记录，防止覆盖其他应用更新。

## 后续工作

本轮仅保证 Media 的 MCP 协议与公网入口可用。MoviePilot MediaCapabilities 公共宿主已由并行业务开发部署。凭据有效性及真实搜索／下载由业务阶段单独验收；普通 API_TOKEN 不能直接当作 JWT。本轮未触发真实下载。

后续业务构建遵守根目录 AGENTS.md 和对应业务目录 AGENTS.md。所有 NAS 目标、访问令牌和业务秘密仍在仓库外。GPT Web 认证适配、插件发布与界面接入验收属于下一阶段。
