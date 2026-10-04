# MCP Platform

公共 FastMCP 运行时及 NAS 部署工具。业务项目维护工具和 `mcp.app.yaml`，通过版本依赖复用公共认证与 HTTP 装配。

首版版本 `0.1.0`，Python 3.12、FastMCP 3.4.4、MCP SDK 1.28.1、Authlib 1.7.2。协议栈和兼容修正一起升级。

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

修改生成项目的 `mcp.app.yaml`，填写域名、宿主端口、Authelia 策略、凭据需求和业务卷；提交 `uv.lock`。SDK 的 Git 来源使用 `v0.1.0`，锁文件记录实际提交，不跟随 main。

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
      personal-crm: /home/yuwk/personal-crm
    env_files:
      personal-crm: /vol2/1000/Docker/personal-crm/.env
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

Tunnel 先验证配置，再通过临时副本更新主连接，保留其他域名路由。启用 DDNS 配置时，仅从 IPv4/IPv6 管理列表移除当前应用域名，然后将该域名 A/AAAA 切换为 Tunnel CNAME；回滚恢复原列表和 DNS。

同版本、环境和入口配置重复部署时只验证，不重建、不重启、不重复注册。部署过程使用宿主机文件锁。

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

插件包仅包含清单生成的元数据、App 绑定、图标、连接地址和中文接入说明；不包含业务代码、env 或数据。已有插件名和 App ID 不匹配时拒绝打包。首次连接需用户登录和同意授权；打包命令不发布到插件市场或创建新 App。

现有连接更新后先使用原连接调用只读工具，再确认刷新。重大协议升级及首次连接需要 GPT/dots 实机确认；不通过删除 App 或清空 OAuth 状态处理问题。

## 首版验收

只执行必要的冒烟验证：HTTP/初始化、权限、两种存储重启、URL client_id、共享文件冲突、模拟部署失败回滚、CRM 隔离读写、生产只读、部署重复执行。命令：`uv run pytest -q tests/test_smoke.py`。

CRM 作为真实示例继续在自己的仓库维护业务实现。SmartSearch、远程执行器与 MCPHub 本轮不迁移。
