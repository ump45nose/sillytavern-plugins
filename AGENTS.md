# 后续 MCP 构建与部署约定

## 本轮范围与架构

- 公共运行时、认证兼容和部署能力统一维护在本项目；业务工具留在业务仓库。业务配置以该服务的一份 `mcp.app.yaml` 为准，应用目录只登记仓库、版本和清单所在子目录。
- 公网 Tunnel 入口与四个私有原生 GPT Web MCP 连接已完成。CRM 使用名称「CRM」与图标 C；远程服务器采用 C 方案「远程工作台」直接连接独立 MCP；钉钉使用官方图标，Media Download 使用 MoviePilot 官方图标。实际网页 App ID、URL 与验证结果见 `docs/gpt-web-rollout-2026-10-05.md` 和 `docs/gpt-web-release-2026-10-05.json` 的 `native_web_connections`。旧展示包 release 仅为历史记录。
- 展示候选存放在 `docs/gpt-web-plugin-drafts/`，仅用于评审。选定后以业务 `mcp.app.yaml` 为正式配置来源，不让候选资料成为第二份部署配置。CRM 与远程服务器使用原创图标，Media Download 原样复用 MoviePilot 官方图标并登记来源；不在图标中加入令牌、域名或设备标识。
- CRM 使用公共运行时；钉钉继续由现有 MCPHub 聚合官方服务，远程网关保留 systemd 与独立执行器。Media Download 业务容器保留 SDK 2.3.0 与文件 Bearer，由 `integrations/media-download-mcp/` 的公共运行时网关提供公网 OAuth；保留原 Bearer 客户端兼容。不要替换业务 SDK、重复运行下载后端或把后端令牌放入插件。
- 钉钉源码与展示统一在 `integrations/dingtalk/`，当前清单在该目录根部，事件生产器在 `events/`，旧根目录插件包在 `legacy-plugin/` 仅留历史。2026-10-08 本次收束仅改变 Git 源码与目录登记，未切换 NAS 私有 source_roots 或用量统计构建路径；后续部署须显式核对并迁移，保留现有 MCPHub、App 身份和 OAuth 状态。旧远程展示包的云端 skill 路径和指引仅保留作历史；原生远程工作台使用实际工具及 MCP 描述，不引用旧 App。
- 复用 `local-env-mcp-cloudflared` 的共享 Tunnel，每个服务使用独立域名直达原进程。不要新建重复 Tunnel、数据库、Redis、反代或聚合网关。

## 版本、构建与配置

- Python 公共运行时使用 Python 3.12、uv。本轮刷新期限能力使用 SDK `v0.1.3`，业务锁定版本及完整 Git 提交；不改写旧发布标签，不让生产依赖跟随 main。
- 私有 Git 依赖由宿主机凭据取得，按锁定提交构建 wheel 后注入镜像。镜像、构建上下文和普通日志不得包含 GitHub／Cloudflare 凭据、生产 env、业务数据或 OAuth 状态。
- NAS 目标、秘密和访问令牌保存在仓库外，目录 700、秘密文件 600。清单只引用秘密；不得把令牌写入 URL、示例、AGENTS.md 或工具输出。
- 如单独维护已有桌面／便携插件包，保留源文件、提示语的类型与顺序、访问范围和已核实映射；包的版本与 release 不替代网页连接的真实身份。
- Media 网关秘密与 OAuth 状态位于仓库外 `~/.config/mcp-platform/media-download-gateway/`；保留签名／存储密钥和 `media-download-oauth-v1` 盐。密钥初始化和共享配置协调使用同一部署锁，升级不恢复旧 OAuth 快照。
- 业务代码存在其他人未提交的修改时，不回退、不批量提交。入口模式只操作清单和路由；涉及业务镜像构建时记录所用文件摘要和镜像 digest，不把未提交源码宣称为已发布版本。
- 无认证开发模式必须显式启用且绑定回环地址；生产缺少认证时拒绝启动。公网入口必须先验证未认证请求被拒绝。
- 刷新期限是应用清单的 `refresh_token_lifetime_days`，默认 180 天；五个现有服务均使用默认。Authelia 使用各客户端独立的受管理 lifespan，钉钉由 `oauth_provider: mcphub` 协调已有北向 OAuth。不要把期限写死在一次性部署脚本中，也不要更改访问令牌期限来代替刷新期限。

## 本次踩坑与后续规则

- **GPT 网页端禁止使用 Plugin Creator**。网页接入使用「创建自定义 MCP 服务器」表单。旧 ZIP／展示包的保存成功只证明包已保存；本次该路径产生了默认图标、Media Download 仅限桌面和远程工作台依赖旧 App 的问题。
- **图标先满足网页限制**：当前原生表单只接受 PNG，上限 10 KB。保留用户选定／官方原图，生成 256×256 压缩副本，上传前核对大小。四个实际上传文件与摘要见 `docs/gpt-web-plugin-drafts/2026-10-04/web-icons/index.json`。验收看详情页和已安装列表的实际图标，不能只看源文件中的 logo/composerIcon。
- **Browser Relay 公网中继可直接操作已登录浏览器**。单个 Mac 工具的 Unknown tool、AppleScript JavaScript 被禁用或辅助功能脚本错误，不代表必须恢复旧远程 App 或切换远程环境。先核对已配置的中继和工具能力，按实际标签页 URL／标题选择 tab ID。重连后重新列举 ID；使用独立任务页／session，尊重其他会话的占用，不抢前台。
- **观察实际执行结果再继续**：DOM click 对部分菜单可能无效，必须确认菜单／对话框出现。按实际 label、placeholder 或 ref 定位；输入框的默认 text 类型不一定有显式 `type="text"` 属性。步骤失败时停止后续依赖步骤；超时后先查任务和页面，避免重复提交。Relay 会话有租约，长时间整理文档时维持心跳；已过期的会话使用新 session 显式继续。设备 capability 从仓库外私有文件读取，不输出或打包。
- **网页身份以实际原生连接为准**。远程工作台直接连接 `https://local-env-home.172906573.xyz/mcp`，不能用旧「远程服务器接入」App 包装。原生 App、旧包装插件和 release ID 是不同身份；记录真实 App ID／版本 ID／网页 URL，再同步业务清单与本地 `.app.json`。后续更新保留本次原生身份，旧包只留历史记录，不生成占位 ID。
- **定位实际网络失败**：容器、宿主机和工具环境的出站路径不一定相同。Media 的 host 网络网关最初未配置代理，抓取 ChatGPT CIMD 文档被重置，页面报 Client Not Registered。复用 NAS 现有 HTTP/HTTPS 代理并存入私有网关 env，NO_PROXY 排除回环与 Authelia，保留 MCP_PROXY_SNI_COMPATIBILITY=true。修复后重试原 OAuth 请求，不关闭 CIMD、PKCE、TLS 或 JWT 校验，也不重复创建 App。
- **匿名冒烟使用 MCP initialize POST**，携带正确 Host、Accept 和 Content-Type；无状态入口 GET 返回 405 不能作为认证失败。一次健康和必要协议检查通过后，不反复测试或重建已经可用的服务。
- **按用户已授权范围继续连接和授权**，不自行添加「首次同意必须用户手工完成」的限制。真实登录／MFA 缺少必要信息时说明具体缺失项。展示资料与服务已经齐备时，集中填网页表单；只对实际发现的问题做最小修复，不扩展成后端重构。
- **验证实际刷新期限**：本次邮件及 Media 的新 Authelia 客户端漏了 `lifespan`，落到默认 90 分钟，隔夜后刷新被拒绝；已有 CRM／远程策略与钉钉刷新当时正常，不能把全部 UI 异常归为同一原因。部署须协调上游策略并在新签发后核对实际期限。新配置不延长已签发令牌；失效连接在原 App 重新授权，不清空状态或重建 App。
- **MCPHub 配置与动态状态共用 JSON**：修改期限时短暂停止进程、比较候选摘要，只改变北向 OAuth 的期限字段后恢复运行。回滚只比较并恢复该字段，保留后来产生的令牌、客户端和用户配置；不得拿旧 JSON 快照覆盖最新 OAuth 状态。
- **两端期限要一致**：FastMCP 3.4.4 未收到上游 `refresh_expires_in` 时，默认按一年签发代理刷新凭据。本次公共运行时与远程兼容适配已显式使用清单期限；验收读取新令牌的非秘密时间元数据。部署时保留原密钥和盐，旧签发令牌不改写，需要立即采用新期限时在原 App 重新授权。
- **基于现有镜像升级运行时**：先按 digest 校验本地基础镜像，再用本地 tag 作为 Dockerfile FROM。BuildKit 会把裸 `sha256:<image-id>` 解释成镜像名并尝试拉取，不能因此重复重建业务或把凭据加进构建。记录 wheel 摘要、源码摘要、原／新镜像及私有回退记录。

## 部署流程

### 1. 准备并部署 NAS 服务

1. 读取业务 `mcp.app.yaml`、应用目录及仓库外 NAS 目标配置，核对当前运行进程、共享设施、数据卷、认证和现有域名。新项目由 `mcpctl init <service>` 初始化；已有服务使用原清单。
2. 在 NAS 本机运行 `mcpctl doctor --target nas`、`mcpctl plan <service> --target nas`，确认真实变更范围。正式 CLI 路径为 `/home/yuwk/code/mcp-platform/.venv/bin/mcpctl`；需要读取受保护的目标配置或协调部署时使用 `sudo -n`。服务仅变更网页资料时复用已经通过的后端结果。
3. 新建／代码更新按锁定依赖构建；已有服务的 existing 模式协调入口与已登记认证配置。远程网关的刷新期限 env／重载绑定保存在 NAS 私有目标，期限变化仅重启网关，不重启执行器。运行 `mcpctl deploy <service> --target nas`；Media OAuth 网关的构建与首次协调使用 `integrations/media-download-mcp/README.md` 的专用流程，镜像 tag 从 Compose 读取，基础镜像必须包含当前锁定公共包并核对 digest。私有依赖凭据由宿主机取得，wheel 注入镜像。
4. 部署持有共享锁并写私有变更记录；更新前备份本次配置，校验 Authelia／Tunnel 候选，只协调目标客户端、刷新期限和域名，保留其他路由。无差异跳过共享设施重启；仅调整认证可运行 `mcpctl deploy <service> --target nas --auth-only`，其回滚也使用 `--auth-only`。失败按摘要比较后恢复本次镜像／配置／DNS，发生外部修改时停止覆盖，业务数据和 OAuth 状态不回退。
5. 做一次必要冒烟：健康、未认证 initialize POST 拒绝、OAuth 发现，以及授权的 initialize／tools/list。核对共享远程路由仍可用；本轮网页发布不触发生产写入、远程执行或下载。

### 2. 逐个接入 GPT 网页

1. 从清单取得名称、完整描述、真实公网 `/mcp` URL、OAuth 设置和定稿图标；准备满足 10 KB 限制的 PNG。参考 `docs/gpt-web-form-values-2026-10-05.json`，以业务清单为源。
2. 用已配置的 Browser Relay 中继定位 ChatGPT Plugins 页面。选择「添加 → 创建自定义 MCP 服务器」，上传图标、填名称和描述、选择「服务器 URL」，填真实 MCP URL，认证选择 OAuth。已存在的原生连接优先使用网页编辑流程。
3. 核对字段和图标无错误后，勾选表单确认并提交一次，继续连接。按实际页面完成服务端 Allow Access、Authelia 接受或 MCPHub 登录／授权；使用既有配置和登录态，凭据不输出或写入发布素材。
4. 完成一个服务再处理下一个。详情页核对名称、描述、图标、已连接账户和「在聊天中试用」；管理页核对真实 MCP URL、OAuth 与 App ID。确认没有桌面限制或旧 App 包装依赖。必要时通过网页「刷新工具」做一次工具发现核对，不用包上传结果代替验收。
5. 将实际 App ID／版本 ID／网页 URL 和验证范围写入 `docs/gpt-web-release-2026-10-05.json` 的 `native_web_connections` 与部署记录；同步业务清单、`.app.json`、README。截图留在仓库外，不发布其他账号信息。保留本次身份供后续更新，区分私有开发模式连接与公开目录发布。
6. 释放本任务的 Relay 标签页／会话，保留用户浏览器页面，不断开业务连接。交付真实网页入口和记录路径，只报告已验证的结果。

## 迁移、更新与回滚

- 迁移前读取现有运行配置、网络、挂载和共享设施。保留业务卷、OAuth 注册、签名密钥、加密密钥及盐、issuer、资源 URL、回调、已核实的原生 App 与插件 ID；旧展示包身份见历史记录。
- Authelia 原 issuer/discovery 和 `28443` 授权端点继续使用。`smartsearch_yuwk`、`smartsearch_identity` 是 CRM／远程网关仍使用的共享策略；SmartSearch 退役不意味着可以删除这些策略。
- 更新共享文件前校验候选副本，并在应用时检查候选生成后的外部修改。使用部署锁和私有变更记录；DNS 同样需要比较后更新和恢复。
- Tunnel 通过副本切换更新，保留其他域名路由。切换到 Tunnel 的域名需从 DDNS A/AAAA 管理列表移除，防止 CNAME 被覆盖。
- 代码／入口回滚只恢复本次镜像、配置和 DNS，不恢复旧业务数据或 OAuth 快照。发生外部修改时停止覆盖并记录原因。
- 钉钉和远程服务器仅更新入口时不重启业务或执行器，不终止常驻终端会话；钉钉北向 OAuth 期限更新可短暂停止 MCPHub 以安全改写共享状态文件。Media Download 验收只做协议初始化和工具枚举，不触发真实下载。

## 验证与交付

- 代码任务只做受影响路径的基本冒烟，禁止大量回归测试和重复开发；没有新变化、失败或疑点时不重复测试。
- 必要检查：清单校验、服务健康或协议响应、未认证拒绝、MCP initialize／tools/list、OAuth 发现（已有 OAuth 服务）、既有共享路由保留。
- 面向使用者的部署、接入、升级、回滚说明使用中文，并同步 README。明确区分 Tunnel 可达、协议通过、业务后端可用和客户端发布，不把它们互相替代。
- SmartSearch 已按用户要求退役；不要从旧备份重新发布它。保留受保护回退备份不代表该服务仍在运行。
