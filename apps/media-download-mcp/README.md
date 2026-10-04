# Media Download MCP

独立的通用 MCP 服务，使用官方 Python SDK 2.3.0，支持 stdio 和 Streamable HTTP。
仅提供 `search_resources`、`download_media`、`get_download_status` 三个工具。
客户端接入、OAuth 和 MoviePilot 原 MCP 调优由其他项目处理。
公共规则见 [获取能力设计](../../docs/media-acquisition.md)。

## 安装与运行

从仓库根目录安装共享 wheel 和锁定依赖：

```sh
python3 -m venv .venv
.venv/bin/pip wheel --no-deps --wheel-dir .build/wheels ./packages/media-capabilities
.venv/bin/pip install --find-links .build/wheels -r apps/media-download-mcp/requirements.lock
.venv/bin/pip install --no-deps -e ./apps/media-download-mcp
```

复制 `config.example.json` 为 `config.json`，配置 MoviePilot 地址和 API 令牌文件。
HTTP 模式另外需要本服务访问令牌文件；文件权限必须为 `0600`，不提交到 Git。
MoviePilot 必须安装共享包 0.3.0、MediaCapabilities 0.1.0 并启用公共宿主。
无需安装或更新 FilmWatchlist；站点、浏览器和 115 设置由公共宿主独立管理。

```sh
# 本机客户端启动的子进程；stdout 仅用于 MCP 协议：
.venv/bin/media-download-mcp --config apps/media-download-mcp/config.json --transport stdio
# 通用远程 HTTP 入口：
.venv/bin/media-download-mcp --config apps/media-download-mcp/config.json --transport streamable-http
# 独立容器，构建上下文为仓库根目录：
docker compose -f apps/media-download-mcp/compose.yaml up -d --build
```

HTTP 地址为 `/mcp`，默认端口 8091，每个请求使用本服务的 `Authorization: Bearer ...`。
NAS 实际配置和令牌位于仓库外的 `MEDIA_DOWNLOAD_RUNTIME_DIR`，保留已有访问令牌。
仓库根目录 Compose 负责业务容器，`mcp.app.yaml` 通过公共部署 CLI 的 existing 模式
接入共享 Tunnel；这不会替换业务 SDK 或创建 OAuth 客户端。
Compose 只发布到本机；配置中 `public_hosts` 需包含实际访问域名/IP，HTTP Origin 检查和
Host 检查由 SDK 执行。访问令牌可以通过替换文件轮换，不使用 URL 查询参数传递。
宿主 API 令牌仅由服务端读取。公网反代与云端 agent 的鉴权适配不包含在此服务中。

## 工具参数

查询和下载的媒体参数放在 `request` 对象中，例如：

```json
{"request": {"tmdb_id": 123, "media_type": "movie", "policy": "quality"}}
```

剧集例子：

```json
{"request": {"title": "剧名", "media_type": "tv", "scope": "season", "season": 2}}
{"request": {"imdb_id": "tt1234567", "scope": "episode", "season": 2, "episode": 3}}
{"request": {"tmdb_id": 123, "media_type": "tv", "scope": "series"}}
```

- `search_resources` 首次给 `request`；返回 `session_id` 后，仅给 `session_id` 续查，
  加 `source_id=mteam|mini4k` 读取下一页。展示阶段不获取种子元数据。
- `download_media` 可给媒体身份自动选源，或给搜索返回的 `candidate_id` 下载指定资源。
  候选范围必须与搜索一致。默认 `quality`，另有 `subtitle`、`balanced`；
  指定候选不受自动偏好限制，仍执行身份、范围、格式、private 与路由检查。
- `get_download_status` 给回执的 `task_id`。提交通常等待接收确认，最多等待 120 秒；
  `pending` 需续查。重试原下载调用应保留 `request_id`，不要在结果未知时另建请求。

无需调用方重新输入已知片名。身份不唯一或模糊匹配时返回候选作品供明确选择。
整剧仅选择已完结剧集的单一完整 BT 资源。新入口不主动清理或替换旧版。

## NAS 与共享 Tunnel

本服务公网地址为 `https://media-download-home.172906573.xyz/mcp`，独立 Docker 容器监听 `127.0.0.1:8091`，共享 Tunnel 直接转发。现阶段保留 SDK 2.3.0 与本服务的文件 Bearer 认证，不接入公共 FastMCP 运行时或 OAuth，也不发布 GPT Web 插件。部署约定见本目录 `AGENTS.md`。

生产配置与秘密放在 `/home/yuwk/.config/mcp-platform/media-download-mcp`，由 `MEDIA_DOWNLOAD_RUNTIME_DIR` 指向。访问令牌在 `secrets/access.token`，宿主凭据在 `secrets/moviepilot.token`，均为 600；客户端以 Authorization 请求头携带本服务令牌，不把令牌放进 URL。MoviePilot 凭据必须是该宿主接受的有效 Bearer 凭据，原 API_TOKEN 不能直接充当 JWT。公共宿主已由业务开发部署；凭据和真实搜索／下载仍按业务阶段单独验收，本轮不调用真实下载。

NAS 当前使用 media-automation 根 Compose 中的 media-download-mcp 服务，容器为 media-automation-media-download-mcp-1；入口由公共基座协调：

```bash
sudo -n env MEDIA_DOWNLOAD_RUNTIME_DIR=/home/yuwk/.config/mcp-platform/media-download-mcp \
  docker compose --project-name media-automation -f /home/yuwk/media-automation/compose.yaml up -d --no-build media-download-mcp
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan media-download-mcp --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy media-download-mcp --target nas
```

`mcp.app.yaml` 是公网入口的唯一来源，实际配置的 public_hosts 包含其域名。首次构建使用受保护的最小源码快照，记录文件 SHA256、wheel 摘要与运行版本；仓库中其他未提交内容未批量提交或回退。运行使用 Python 3.12，业务锁定依赖不变。容器读取 config.json 和 secrets；首次构建的受保护源码与 wheel 位于上述私有目录的 builds／wheels。

入口验收检查匿名请求 401、带令牌 initialize 和三个工具枚举，不触发真实下载。入口回滚使用 `mcpctl rollback media-download-mcp --target nas`，只恢复本次 Tunnel／DNS，不停止业务服务或恢复数据。业务镜像更新和后端宿主更新独立管理。

容器配置的 host 为 0.0.0.0，宿主端口仍仅绑定回环地址。Tunnel 接入期间曾因镜像站与构建器故障临时使用 systemd；业务部署随后切换为 Docker，临时 systemd 已停用。deploy/media-download-mcp.service 仅作备用参考，不与容器同时启用。
