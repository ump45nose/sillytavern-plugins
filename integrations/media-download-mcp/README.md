# Media Download OAuth 网关

公网地址保持 `https://media-download-home.172906573.xyz/mcp`。共享 Tunnel 转发到回环 `127.0.0.1:8092` 的公共运行时网关；原 SDK 2.3.0 下载后端继续在 `127.0.0.1:8091` 运行，网关使用服务器端的原文件 Bearer 私下访问后端。没有新建下载后端、数据库或 Tunnel。

业务与正式应用清单在 `/home/yuwk/media-automation/apps/media-download-mcp/`。本目录只维护 OAuth 代理、容器装配与首次协调脚本。网关保留四个工具的名称、输入结构与结果，`search_resources`、`get_download_status` 要求读权限，`download_media`、`check_media` 要求写权限。`check_media` 按要求复制下载实现，因此也可能提交下载。只读身份在请求后端前被拒绝下载；超时 180 秒，不自动重试写入，不截断原输出。

## 构建和更新

使用 NAS 已有锁定运行时镜像 `local/personal-crm:refresh-policy-0.1.3`，基础镜像 SHA256 为 `05c8ddd875743c4635fb12ce5ac21b5c383055227aaa5b7d6064b3c1c7c1f888`。其中公共包为 `0.1.3`、FastMCP 为 `3.4.4`、MCP SDK 为 `1.28.1`；下载后端的 SDK 版本保持 `2.3.0`。脚本在部署前校验基础镜像摘要。构建上下文仅含 Dockerfile 与网关源码，不含秘密、OAuth 状态或业务数据。

```bash
MEDIA_GATEWAY_IMAGE=$(/home/yuwk/code/mcp-platform/.venv/bin/python -c \
  'from pathlib import Path; import yaml; print(yaml.safe_load(Path("/home/yuwk/code/mcp-platform/integrations/media-download-mcp/compose.yaml").read_text())["services"]["gateway"]["image"])')
sudo -n env DOCKER_BUILDKIT=0 docker build --pull=false \
  -t "$MEDIA_GATEWAY_IMAGE" \
  /home/yuwk/code/mcp-platform/integrations/media-download-mcp
sudo -n /home/yuwk/code/mcp-platform/.venv/bin/python \
  /home/yuwk/code/mcp-platform/integrations/media-download-mcp/deploy_gateway.py
```

首次生成的签名、存储及 OIDC 密钥在仓库外 `/home/yuwk/.config/mcp-platform/media-download-gateway/gateway.env`，OAuth 状态在同目录 `oauth/`；目录 700、秘密文件 600。后续复用原密钥、注册和 `media-download-oauth-v1` 盐。原访问令牌仍为 `/home/yuwk/.config/mcp-platform/media-download-mcp/secrets/access.token`，只读挂入网关；不放入插件或 URL。原 Bearer 客户端继续使用同一入口，映射到显式配置且已授权的原账号。

刷新期限由业务清单 `refresh_token_lifetime_days` 指定，默认 180 天。公共网关与 Authelia 使用同一期限；已签发令牌不会随配置延长，需立即采用新期限时在原网页 App 重新授权。日常仅修改期限可运行 `mcpctl deploy media-download-mcp --target nas --auth-only`，由仓库外目标中的 env／重载绑定协调，无差异跳过重启。

协调脚本先取得共享部署锁，再读取清单和初始化密钥；只添加 Authelia 客户端 `media-download-mcp`，保留原 issuer、`28443` 授权端点、模板、策略及其他客户端。Authelia 和 Tunnel 候选经官方校验后写入，Tunnel 通过副本切换。共享文件发生外部修改时停止覆盖；失败恢复本次配置，业务数据和 OAuth 状态不恢复旧快照。

首次协调记录位于 `/vol2/1000/Docker/stacks/mcp-platform/runtime/media-download-mcp/releases/20261004T155524466423/journal.json`，为私有文件，不输出其原始内容。`mcpctl rollback media-download-mcp --target nas` 可以按变更记录恢复入口；若共享配置或源清单在此后已改变，先停止覆盖并人工核对差异，不强制恢复整份快照。入口回退不停止原下载后端，未被路由引用的网关应单独停止；保留其 OAuth 数据。

## GPT 网页端

2026-10-05 已通过原生 MCP 表单注册并完成 OAuth：[打开 Media Download](https://chatgpt.com/plugins/plugin_asdk_app_6ac288ae39908191a239ef999f71fa54)。实际 App ID 为 `asdk_app_6ac288ae39908191a239ef999f71fa54`；MoviePilot 官方图标、已连接账户和网页「在聊天中试用」已确认。清单与本地 `.app.json` 已同步该身份，后续网页部署禁止使用 Plugin Creator。

旧展示包 `plugins_6ac2796ae06c81918dc636d8ab8e8ceb` 的 `0.1.0` release 仅为历史包，曾显示仅限桌面；其 ID 不是本次原生网页身份。详细入口与上传图标见平台 `docs/gpt-web-rollout-2026-10-05.md`。

host 网络网关需要访问 ChatGPT 的 CIMD/JWKS 文档。私有 `gateway.env` 已复用 NAS 现有 HTTP/HTTPS 出站代理，`NO_PROXY` 包含回环及 Authelia，`MCP_PROXY_SNI_COMPATIBILITY=true` 保留 TLS 与签名校验；部署脚本会保留这些既有 env。最初的 `Client Not Registered` 来自缺失代理导致连接重置，补配置并重试原 OAuth 请求后成功，未重建下载后端。成功变更记录：`/vol2/1000/Docker/stacks/mcp-platform/runtime/media-download-mcp/releases/20261004T171916-outbound-proxy/journal.json`。

本次变更后健康 200，未认证 MCP initialize POST 401；无状态入口 GET 返回 405 不代表认证失败。此前基础协议、原 Bearer 兼容和隔离权限冒烟已通过；本次没有触发真实下载或生产写入。

2026-10-05 工具与描述更新使用业务镜像 `local/media-download-mcp:0.1.3-check-media`、网关镜像 `local/mcp-platform-media-download-gateway:check-media-0.1.3`。更新持有既有部署锁，仅替换两个业务容器；原 OAuth 配置与数据保留。公网匿名 initialize 401、授权 initialize 和四个工具描述已验证，未调用真实下载。GPT 展示名现为 Media Tool，名称和描述由用户修改并确认；本地正式清单同步该展示名。源码摘要、旧／新镜像 ID 与协议结果位于业务仓库 `.build/check-media-20261005/`。
