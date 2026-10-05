# MCP Platform

公共 FastMCP 运行时及 NAS 部署工具。业务项目维护工具和 `mcp.app.yaml`，通过版本依赖复用公共认证与 HTTP 装配。

首版版本 `0.1.0`，Python 3.12、FastMCP 3.4.4、MCP SDK 1.28.1、Authlib 1.7.2。协议栈和兼容修正一起升级。

本轮公共运行时及 NAS 部署 CLI 更新为 `0.1.3`，支持可配置的刷新期限（默认 180 天），在写入前校验候选配置，检查候选生成以来的外部修改。生成项目使用 `v0.1.3`，业务依赖锁定该版本及实际提交；既有 `v0.1.0`／`v0.1.2` 标签不改写。

## 安装与新建服务

```bash
gh repo clone ump45nose/mcp-platform
cd mcp-platform
gh auth setup-git
uv sync --python 3.12
uv run mcpctl init my-service
cd my-service
cp .env.example .env
uv sync --python 3.12
uv run my-service-server
```

本地无认证模式需要显式 `MCP_DEVELOPMENT_NO_AUTH=true`，只能监听回环地址，不能设置公网地址。生产缺少认证配置时拒绝启动。

修改生成项目的 `mcp.app.yaml`，填写域名、宿主端口、Authelia 策略、凭据需求和业务卷；提交 `uv.lock`。SDK 的 Git 来源使用 `v0.1.3`，锁文件记录实际提交，不跟随 main。

```python
from mcp_platform import RuntimeConfig, authorize, create_server, create_http_app

config = RuntimeConfig.from_env("my-service")
server = create_server(config, healthcheck=lambda: {"status": "ok"})

@server.tool(auth=authorize("read", config))
def lookup(query: str) -> dict:
    return {"query": query}

app = create_http_app(server, config)
```

`create_server` 支持业务 lifespan。已有 FastAPI 可以像 CRM 一样挂载返回的 HTTP 应用，并在父应用 lifespan 中进入子应用 lifespan。

权限 `read`、`write`、`execute` 是业务权限，来自已验证的上游用户名；不是客户端自行声明的身份，也不会改变现有 OIDC identity scopes。执行权限需额外填写 `OIDC_EXECUTE_USERNAMES`，只读用户不能写入或执行。

## NAS 目标初始化

目标文件默认位于 `~/.config/mcp-platform/targets.yaml`，凭据引用独立的 600 权限 env 文件，目录权限 700。`sudo` 下使用原登录用户的默认路径，也可通过全局 `--targets` 指定。

```yaml
targets:
  nas:
    source_roots:
      personal-crm: /yuwk/code/mmp/personal-crm
      dingtalk: /yuwk/code/mmp/dingding-workspace-plugin/mmp-platform
      local-env-mcp: /home/yuwk/mcp-platform/integrations/local-env-mcp
      media-download-mcp: /home/yuwk/media-automation/apps/media-download-mcp
    env_files:
      personal-crm: /vol2/1000/Docker/personal-crm/.env
    probe_token_files:
      media-download-mcp: /path/to/private/access.token
    runtime_root: /vol2/1000/Docker/stacks/mcp-platform/runtime
    platform_repo: /home/yuwk/mcp-platform
    build_user: yuwk
    uv: /home/yuwk/.local/bin/uv
    tunnel_config: /path/to/cloudflared/config.yml
    tunnel_compose: /path/to/cloudflared/compose.yml
    tunnel_container: local-env-mcp-cloudflared
    tunnel_id: EXISTING_TUNNEL_UUID
    authelia_config: /path/to/authelia/configuration.yml
    cloudflare_env: /path/to/private/cloudflare.env
    cloudflare_zone_id: EXISTING_ZONE_ID
    ddns_config: /path/to/ddns-go/config.yaml
```

Cloudflare env 使用 `CLOUDFLARE_API_TOKEN`；也支持现有基础设施的 `CLOUDFLARE_EMAIL` 与 `CLOUDFLARE_API_KEY`。新凭据优先使用指定 zone 的 DNS 编辑权限。Tunnel 使用宿主机已有 credentials，不创建新 Tunnel。

业务 `env_files` 未登记时，CLI 在目标 runtime 目录首次生成独立 OAuth 凭据，以后复用；业务凭据仍需要首次填写。已有 env 文件不会生成、替换或轮换密钥。

## 刷新令牌期限

应用清单的 `refresh_token_lifetime_days` 为部署配置，省略时默认 **180 天（半年）**。CRM、远程工作台、Media Download、邮件及钉钉均使用此默认值；需要其他期限时在该服务的 `mcp.app.yaml` 显式覆盖，例如：

```yaml
refresh_token_lifetime_days: 90
```

访问令牌仍使用原有短期限，客户端通过刷新保持连接。Authelia 部署为目标客户端生成独立的 `mcp_platform_<client_id>` lifespan，并协调 `refresh_token` 及已有 grant override；保留原访问／ID／授权码期限、其他客户端、模板和策略。公共运行时从清单生成的 `OAUTH_REFRESH_TOKEN_LIFETIME_DAYS` 取得同一期限，用于上游未返回刷新期限时的 FastMCP 兜底。

已有 Media／远程网关的 NAS 目标通过 `auth_runtime_env_files` 引用原 env，通过 `auth_reload_commands` 登记网关重载命令；部署从清单生成同一期限并重载网关，不维护第二份期限配置。远程网关目前使用集成目录的 `refresh-policy.patch` 兼容现有认证装配，保留其盐、存储和独立执行器。构建模式通过 Compose 的清单 environment 注入期限，变更该模式的运行时配置应使用常规部署。

钉钉清单声明 `oauth_provider: mcphub`；NAS 私有目标登记 `mcphub_config` 与 `mcphub_container`。MCPHub 当前使用共享的北向 `refreshTokenLifetime`（秒），并无逐客户端期限配置。更新时短暂停止该容器避免与令牌写入竞争，保留全部注册、令牌和钉钉后端设置，启动后采用新配置；无差异不重启。回滚只恢复该配置字段，保留更新后生成的 OAuth 状态。

`mcpctl plan` 显示期限和认证变更；常规 `deploy` 会协调清单已登记的提供方。仅调整期限、不构建业务镜像或更新入口时使用：

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy personal-crm --target nas --auth-only
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl rollback personal-crm --target nas --auth-only
```

**新期限用于后续签发的令牌，不能延长或复活已签发的旧令牌。** 需要立即取得半年授权的连接，在原 App 上重新授权；保持 App ID、域名、回调、密钥及状态，不重新创建插件。更新后核对实际新令牌期限，不能仅以首次连接或发现文档中的 `refresh_token` 声明作为验收。

## 预检、部署与回滚

共享配置及现有 CRM env 为管理员所有，因此这些 NAS 命令使用管理员权限；构建步骤内部降权到 `build_user`。

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl doctor --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan personal-crm --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy personal-crm --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl rollback personal-crm --target nas
```

`plan` 只读；`deploy` 要求业务仓库没有未提交修改。公网 URL、OIDC discovery/client、回调及插件连接信息由清单生成，清单 environment 无需重复填写这些字段。

部署会在宿主机按 uv.lock 构建业务和基座 wheel，容器安装锁定的依赖与 wheel。GitHub 凭据、业务 env、Git 目录和 OAuth 数据均不进入构建上下文或镜像。

部署保留业务卷，创建业务数据与 OAuth 状态的私有备份；只协调当前 Authelia 客户端，配置一致时不重启 Authelia。新增客户端必须引用已存在的授权及声明策略。现有客户端配置冲突时失败，不自动改变身份策略。

Authelia 与 Tunnel 候选文件先用现有容器／镜像的官方命令校验，再写入生效配置。候选生成后共享文件发生变化时停止覆盖；不将外部变化记为本次部署的原配置。

Tunnel 先验证配置，再通过临时副本更新主连接，保留其他域名路由。启用 DDNS 配置时，仅从 IPv4/IPv6 管理列表移除当前应用域名，然后将该域名 A/AAAA 切换为 Tunnel CNAME；回滚恢复原列表和 DNS。

同版本、环境和入口配置重复部署时只验证，不重建、不重启、不重复注册。部署过程使用宿主机文件锁。

## 已有服务的 Tunnel 接入

`deployment_mode: existing` 使用当前业务进程。`deploy` 协调 Tunnel、DDNS、DNS，以及清单已登记的 OAuth 刷新期限；没有登记 auth 的已有 Authelia 服务保持原认证。先验证本机协议、匿名拒绝，再更新入口并验证公网。OAuth 服务检查发现文档与原 issuer；Bearer 服务使用目标文件中的 `probe_token_files` 私下验证 initialize／tools/list。回滚只恢复本次配置，保留业务数据及最新 OAuth 状态。

```yaml
schema_version: 1
id: my-existing-mcp
name: 已有 MCP
deployment_mode: existing
authentication: bearer
public_url: https://my-existing-mcp.example.com
host_port: 8091
bind_address: 127.0.0.1
health_path: ''
mcp_path: /mcp
expected_tools: [search_resources, download_media, get_download_status]
```

该模式要求已有服务先启动，公共 CLI 不构建或管理它的业务镜像／systemd。实际配置的 Host 白名单应包含清单域名；凭据仅用请求头传递。应用目录可用 `path` 登记清单在业务仓库内的子目录；本机目标的 source_roots 可直接指向该子目录。

新域名可能暂时命中旧通配 DDNS。公网检查最多等待五分钟处理 DNS／TLS 传播，始终验证证书和域名，失败时回滚入口；不会把令牌发送到证书校验失败的地址。

| 服务 | 公网 MCP 地址 | 当前运行与认证 |
|---|---|---|
| CRM | `https://crm-home.172906573.xyz/mcp` | Compose，公共运行时与 Authelia |
| 钉钉 | `https://mcphub-home.172906573.xyz/mcp` | 原 MCPHub 与北向 OAuth |
| 远程服务器 | `https://local-env-home.172906573.xyz/mcp` | 原 systemd 网关／执行器与 Authelia |
| Media Download | `https://media-download-home.172906573.xyz/mcp` | 原 SDK 2.3.0 业务容器 + 公共 OAuth 网关，兼容原文件 Bearer |

后三者使用已有服务模式，业务进程仍独立维护。Media 公网回源现为 `127.0.0.1:8092` OAuth 网关，网关私下调用原 `127.0.0.1:8091` 后端；[网关部署说明](integrations/media-download-mcp/README.md)记录构建、密钥保留与回退。MoviePilot 公共宿主已由业务开发部署，业务配置和真实下载单独验收，不把工具枚举通过视为真实下载可用。

四个服务已在 ChatGPT 原生 MCP 表单注册并完成 OAuth 连接：CRM 与远程工作台使用已选 C 图标，钉钉使用官方图标，Media Download 使用 MoviePilot 图标。四者均可在网页「在聊天中试用」；远程工作台直接连接自己的 MCP，Media Download 不再仅限桌面。实际入口与身份见 [网页部署结果](docs/gpt-web-rollout-2026-10-05.md)、[验证记录](docs/gpt-web-release-2026-10-05.json)及[表单值](docs/gpt-web-form-values-2026-10-05.json)。后续网页部署禁止使用 Plugin Creator，规则与本次踩坑见 [AGENTS.md](AGENTS.md)。

SmartSearch 已退役：NAS 容器、NPM 入口、DNS、DDNS 管理与独立 Authelia 客户端移除，NAS／Mac 工作目录移入私有回退备份，GitHub 仓库归档。`smartsearch_yuwk`／`smartsearch_identity` 仍被 CRM 和远程网关使用，保留共享策略；上游 smart-search CLI 是独立工具，不随该自建服务删除。

失败会恢复本次镜像、共享配置和 DNS。文件及 DNS 恢复前检查是否发生外部修改，发生冲突时停止覆盖并记录 `needs_attention`。网络中断导致 DNS 操作结果不确定时，可能需要人工核对，不能把外部变更当成本次变更覆盖。

发布记录位于目标 runtime 的 `<app>/releases/<timestamp>/journal.json`，完整诊断 `error.log` 及备份均为 600 权限。代码回滚不会恢复旧业务数据库或 OAuth 状态，避免覆盖部署期间的写入和新授权。

首版是 NAS 本机 Compose、单实例业务进程。业务和 Tunnel 更新允许短暂连接重建；未提供跨主机 SSH 部署、分布式限流或数据库自动逆向迁移。业务迁移命令必须向后兼容旧镜像，破坏性迁移需单独处理。

## 运行策略与客户端接入

默认审计仅包含身份摘要、工具名、耗时、结果状态；默认每身份每分钟 60 次、工具 60 秒、输出 256000 字节。配置为 0 可关闭对应约束。超时报告结果未知，不自动重试写入；超大输出不会静默截断成错误的结构。CRM 迁移关闭新增限制以保持原调用行为。

FileTree、DiskStore 均保留各自格式；通过 `storage_salt` 复用旧加密盐。注入 `client_storage` 时调用方提供完整后端，平台不重复套加密或关闭调用方拥有的后端。FileTree 采用 URL 安全的文件名策略，支持 CIMD client_id。

FastMCP 3.4.4 的 CIMD `/token` audience 修正集中在 `compat.py`。HTTP 代理场景可显式开启 `MCP_PROXY_SNI_COMPATIBILITY=true`，仅支持已核验的 httpcore 1.0.9，保持 TLS 验证和固定公网 IP。升级依赖时必须复核这些修正。

```bash
uv run mcpctl package personal-crm --target nas
```

插件包仅包含清单生成的元数据、核实的 App 绑定或便携 `mcp.json`、图标、连接地址和中文接入说明；不包含业务代码、env 或数据。没有 App 绑定的新 OAuth 服务使用真实 MCP 端点，不生成空 App 声明。已有插件名和 App ID 不匹配时拒绝打包。连接时按网页 OAuth 流程继续；打包命令不发布到插件市场或创建新 App。更新已有云端插件采用改动文件覆盖包，保留原技能和集成文件。

现有连接更新后先使用原连接调用只读工具，再确认刷新。重大协议升级及首次连接需要 GPT/dots 实机确认；不通过删除 App 或清空 OAuth 状态处理问题。

## 首版验收

只执行必要的冒烟验证：HTTP/初始化、权限、两种存储重启、URL client_id、共享文件冲突、模拟部署失败回滚、CRM 隔离读写、生产只读、部署重复执行。命令：`uv run pytest -q tests/test_smoke.py`。

CRM 作为真实示例继续在自己的仓库维护业务实现。首轮完成 CRM 公共运行时迁移；随后登记钉钉、远程网关和 Media 的公网入口。

本次 NAS 部署和客户端验证结果见 [首次迁移验收记录](docs/validation-2026-10-04.md)。

后续 Tunnel 接入及 SmartSearch 退役结果见 [入口迁移记录](docs/tunnel-rollout-2026-10-04.md)。后续构建约定见 [AGENTS.md](AGENTS.md)。

## 邮件 MCP 更新与迁移

邮件已从 `mcp-email-server 1.4.1` 升级为锁定的正式版 `1.11.0`，由 `integrations/email-mcp/` 的同进程薄适配接入公共运行时 `v0.1.0`。原项目及上游业务代码不改写。新服务运行在平台 Compose，使用回环端口 9557、现有 `tool_net` 与原出口代理；四账号及原策略保留，原数据目录保留。

公网入口为 `https://email-home.172906573.xyz/mcp`，共享 Tunnel 已接入，匿名请求返回 401，OAuth 发现与 19 个工具桥接已通过。Compose 清单支持可选 `user`、`working_dir`、`init`、`external_networks`；目标配置可用 `compose_files` 指定稳定 Compose 文件，更新只协调目标服务。新版 schema v5 使用独立迁移副本，业务卷与 OAuth 卷分别持久化；常规回滚必须使用兼容 v5 的镜像，不能将旧库倒灌。

GPT 网页按“创建自定义 MCP 服务器”表单接入，名称“邮件”，使用 Zoho Mail 官方图标；禁止调用 Plugin Creator。邮件已在真实网页注册并由用户完成 OAuth，官方图标、已连接账户与 19 个工具已核对，[打开邮件插件](https://chatgpt.com/plugins/plugin_asdk_app_6ac285e95d74819193f153ce16dc5640)。客户端账号发现及一次 INBOX 查询已通过，返回 4 个账号、1 个文件夹，未触发邮件写操作。实际状态、构建摘要及回滚说明见 [邮件部署记录](docs/email-mcp-rollout-2026-10-05.md)及[适配说明](integrations/email-mcp/README.md)。
