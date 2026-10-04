# Media Download MCP 构建与部署约定

- 业务实现和锁定依赖在此目录维护；本阶段使用 SDK 2.3.0 与原文件 Bearer 认证，不替换为公共 FastMCP 运行时或 OAuth。
- `mcp.app.yaml` 是公网接入的唯一清单，公共基座 existing 模式仅协调共享 Tunnel／DNS。当前 NAS 使用 media-automation 根 Compose 的独立业务容器；备用 systemd 已停用，不同时运行两个业务进程。
- NAS 秘密和实际配置位于仓库外，由 `MEDIA_DOWNLOAD_RUNTIME_DIR` 引用。访问令牌与 MoviePilot 凭据分开，600 权限；不提交、打印或放进 URL。
- 构建上下文不得包含 config.json、secrets、env、数据库或其他生产资料。记录构建文件摘要与镜像 digest；不要批量提交或回退仓库中其他人的未提交开发。
- 公网 Host 必须加入实际配置的 public_hosts；业务进程或容器的宿主端口仅绑定回环地址，由共享 Tunnel 转发。
- 本轮只验收匿名拒绝、initialize 和 tools/list，不触发真实下载、不安装或升级 MoviePilot 插件。明确区分公网协议验收与业务后端／下载验收。
- GPT Web App／插件下一阶段处理。只做基本冒烟，不做大量回归；修改部署流程同步中文 README。
