# MCP 描述与 check_media 更新 · 2026-10-05

插件展示名称为 **Media Tool**，总描述为「检索媒体信息、提交下载并查询进度。」
GPT 名称与描述由用户在原连接修改并确认；正式清单和本地插件展示文件同步该结果，
App ID 仍为 `asdk_app_6ac288ae39908191a239ef999f71fa54`。

| 工具 | 描述 |
|---|---|
| `search_resources` | 检索服务器上的媒体资源，返回候选引用、字幕信息及查询状态。 |
| `download_media` | 提交媒体下载任务。使用 candidate_id 指定候选，或根据片名、TMDB/IMDb 标识及偏好检索、选择资源并提交到下载器。 |
| `check_media` | 查询媒体信息。使用 candidate_id 指定候选，或根据片名、TMDB/IMDb 标识及偏好检索、选择资源。 |
| `get_download_status` | 查询指定任务的下载状态。 |

`check_media` 按用户要求完整复制 `download_media` 的参数和执行代码，调用相同的
`bridge.download`，因此也会提交下载；MCP 标记与 OAuth 网关均保留写权限要求。

业务后端升级至 **0.1.3**，使用 `local/media-download-mcp:0.1.3-check-media`；
网关使用 `local/mcp-platform-media-download-gateway:check-media-0.1.3`。
构建复用运行中镜像的既有依赖，仅加入后端 wheel 与网关源码；更新持有公共部署锁。

只做受影响路径的基本冒烟：内存 MCP 核对描述、四个工具、参数结构及模拟桥接调用；
公网核对健康、匿名 initialize 返回 401、授权 initialize 与四个工具的描述。
所有检查通过，没有执行真实下载或大量回归。

文件 SHA256、旧／新镜像 ID 与公网协议摘要保存在 `.build/check-media-20261005/`。
原域名、OAuth 状态、认证配置与 MoviePilot 后端配置保留。
