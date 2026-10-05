# Media Download MCP 构建与部署约定

- 业务实现和锁定依赖在此目录维护；后端继续使用 SDK 2.3.0 与原文件 Bearer，不替换业务 SDK。公网由 `/home/yuwk/mcp-platform/integrations/media-download-mcp/` 的公共运行时网关提供 OAuth，代理现有三个工具并兼容原 Bearer 客户端。
- `mcp.app.yaml` 是公网接入与展示配置的唯一清单，当前公网端口为回环 8092；业务后端仍为回环 8091，使用 media-automation 根 Compose 的独立容器。公共基座 existing 模式协调共享 Tunnel／DNS，网关构建与认证协调见公共项目的集成说明。备用 systemd 已停用，不同时运行两个下载后端。
- NAS 秘密和实际配置位于仓库外，由 `MEDIA_DOWNLOAD_RUNTIME_DIR` 引用。访问令牌与 MoviePilot 凭据分开，600 权限；不提交、打印或放进 URL。
- 构建上下文不得包含 config.json、secrets、env、数据库或其他生产资料。记录构建文件摘要与镜像 digest；不要批量提交或回退仓库中其他人的未提交开发。
- 公网 Host 必须加入实际配置的 public_hosts；业务进程或容器的宿主端口仅绑定回环地址，由共享 Tunnel 转发。
- 本轮只验收匿名拒绝、initialize 和 tools/list，不触发真实下载、不安装或升级 MoviePilot 插件。明确区分公网协议验收与业务后端／下载验收。
- GPT 网页已通过原生 MCP 表单注册并完成 OAuth，实际 App ID 为 `asdk_app_6ac288ae39908191a239ef999f71fa54`；MoviePilot 官方图标和网页可用状态已确认。后续网页部署禁止使用 Plugin Creator，保持实际原生身份，旧 `0.1.0` 展示包 release 仅为历史记录。插件不得携带后端或 MoviePilot 凭据。
- OAuth 状态与签名／存储密钥位于仓库外 `~/.config/mcp-platform/media-download-gateway/`；保留 `media-download-oauth-v1` 盐，升级和回滚不恢复旧 OAuth 状态。只做基本冒烟，不做大量回归；修改部署流程同步中文 README。

- host 网络网关的 CIMD/JWKS 请求复用 NAS 现有出站代理；代理留在私有 gateway.env，NO_PROXY 排除回环与 Authelia，保留 SNI、TLS、PKCE 和签名校验。Client Not Registered 先检查元数据抓取错误，不重复创建网页 App。
