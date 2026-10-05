# MoviePilot V2 片单自动收藏插件

将 Favsync 的 `GET /v1/films` 片单接入 MoviePilot V2，比较 Mini4K 与 M-Team 资源，并按来源提交下载。代码位于 `plugins.v2/filmwatchlist`；MoviePilot V2 使用 `FilmWatchlist` 插件 ID。

**v1.4.3 配置边界：**先安装共享包 0.3.1 与独立 `MediaCapabilities` 公共宿主。
站点 ID、Mini4K／Relay、115 路由和目录、分享开关及质量参数由公共宿主统一管理；
本插件保留扫描、预览、调度、Favsync、身份提示和是否使用公网选源。
旧配置和记录补充迁移且原数据保留，具体步骤见 [公共宿主部署](media-acquisition.md)。
网页／MCP 无需安装本插件；使用片单时只需本次完成一次接入更新。

## 行为

- 默认启用“仅预览”，先显示媒体识别结果、所选种子和前五个被拒候选。取消预览后，才会向现有下载器提交任务。
- 仅搜索配置的 M-Team 站点；质量顺序为 Remux 优先，其次按 2160p、1080p、720p 等分辨率与来源排序。同档再比较 HDR、音轨和做种数。
- 媒体识别先核对片名与上映年，再读取详情；片单提供上映日期、国家或类型时一并核对。例如同名的 2024 年电影与剧集可用 `country=法国`、`media_type=movie` 消歧。
- MoviePilot 元数据搜索暂时不可用时，可在“已核实媒体 ID”中按片单 ID 填入豆瓣或 TMDB ID；插件仍逐项核对片名、年份、国家和类型。一次成功识别后会复用已保存的媒体 ID。
- 已上映作品遇到元数据空响应会有限重试；仍失败时，插件会独立查询 M-Team 标题结果并记录数量，以区分“站点有资源”和“媒体身份尚未确认”。身份无法确认时保持跳过。
- 拒绝 ISO、BDMV、DVD 原盘结构。获取并解析种子文件清单失败时跳过候选。电影需要 MKV/MP4；剧集需要第一季完整集数可核实。
- 下载器接收任务后保留任务哈希；只有目标影片或完整目标季已在 MoviePilot 配置的媒体服务器中，才向片单 API 写入 `downloaded=true`。同媒体已有下载历史时不重复入队。本版不洗版。

## 本机部署

片单令牌是独立 Bearer token，不是 MoviePilot 登录密码。运行实例从 `/config/filmwatchlist.token` 读取令牌；文件不进入插件仓库、配置表单或日志。源码安装副本位于 `/config/local-plugins`，MoviePilot 的 `PLUGIN_LOCAL_REPO_PATHS` 指向该目录，并通过 `local://FilmWatchlist?path=/config/local-plugins&version=v2` 安装。插件可在 MoviePilot 界面配置片单 API 地址、扫描间隔和立即运行；站点参数在公共宿主中配置。

部署后先以预览模式运行一次并检查插件详情页。确认候选正确后关闭预览、立即运行一次。MoviePilot 下载和媒体库扫描完成后，后续定时扫描会回写片单状态。

## Mini4K 公网索引预览

`public_index.py` 定义 `PublicIndexer.search / resolve / health`、媒体查询、候选和链接状态。搜索逐页收集同名结果并核对片名、年份、类型、国家及页面可见的媒体 ID；`resolve` 只解析指定候选，区分磁力、实际种子文件、115 分享和其他网盘链接。种子会解析 info-hash、文件清单与 private 标志。Cloudflare、登录、页面变化及无结果各自返回不同状态。候选 ID 可在插件重启后继续解析。

受 MoviePilot 鉴权保护的 `GET /api/v1/plugin/FilmWatchlist/public_health`、`/public_search` 和 `/public_resolve` 保留为兼容委托，可查看公共索引状态与原始证据。在公共宿主中打开 Mini4K 预览后，MoviePilot 的“站点中搜索资源”也会出现预览。站点条目的下载地址为空，仅用于查看；正式提交使用片单、查询网页或下载 MCP 的核验链路。

Linux 复用 MoviePilot 已有 CloakBrowser 与 Xvfb（DISPLAY），使用独立配置目录 `/config/filmwatchlist-mini4k-cloak-browser`，权限为 `0700`；会话数据不写入插件记录或日志。出现 CF 验证页时，通过 CDP 可访问性树识别验证 iframe 内真实 checkbox（包括 closed shadow root），根据实际控件位置输入，等待最终页面，最多点击两次。已在主站实测自动通过一次 CF，并确认重启浏览器后保留 clearance。无法通过仍返回 `CF_CHALLENGE`，不保证所有挑战均可通过。CF 通过不等于已登录；主站与镜像未登录的资源页仍可能返回 `AUTH_REQUIRED`。索引默认使用可公开搜索的 `mini4k.io`；可在设置中改为主站。

可将 Browser Relay 的 Remote Device ID 仅存放在容器内 `/config/filmwatchlist-browser-relay.device-id`（普通文件、权限 `0600`）。Linux 页面访问或资源解析遇到 CF／登录要求时，插件会复用一个 Chrome 专用 Mini4K 标签；标签 ID 保存在权限 `0600` 的 `/config/filmwatchlist-browser-relay.tab-id`。搜索镜像与已登录主站的 Cookie 互不共享，解析会尝试允许的 Mini4K 域名，并将已核实可下载的最终域名保存到权限 `0600` 的 `/config/filmwatchlist-browser-relay.download-origin`，后续优先复用。不会复制 Cookie 到其他域名。

v1.3.1 对 CF 验证页通过 Browser Relay 的可访问性树定位 `challenges.cloudflare.com` iframe 中的真人验证 checkbox，先聚焦并核实标签可见，再执行真实点击，重新读取页面确认已离开挑战页；每次导航最多处理两次。Chrome 窗口最小化时，Relay 的 focus/click 可能仍返回 completed，插件不会据此误报验证通过；保持后台时继续返回 `CF_CHALLENGE`。正常页面嵌入 Turnstile 脚本不会被误判为 CF 挑战。下载使用浏览器跳转后的实际域名，并复用刚读取的资源页。受登录保护的解析可使用已登录 Chrome 后备会话；两个传输均失败时，reason 会分别列出 Linux 和 Browser Relay 状态。

`public_health` 的 `page_status` 只表示页面访问，`resolve_status` 表示该运行实例最近一次资源解析结果；尚未解析时为 `NOT_CHECKED`。主页可访问不等于下载权限正常，最近解析被 CF／登录阻断时总体状态也会保留该故障。磁力中的重复 HTML 转义会先解码，保留实际 tracker 参数后再取元数据；只有核实文件清单与 `private=false` 的资源才能提交 115。

Mac 的已登录浏览器经公网 browser-relay 验证了 2024 年法国版《基督山伯爵》的资源表、Remux 磁力链接与夸克分享链接；容器内的 Linux 搜索加 Relay 解析路径也已完成实站冒烟。索引预览入口仍只返回证据，不直接提交 115 任务。

2026-09-30 修复后的运行实例验证：`public_resolve` 对资源 `962326` 返回 `OK/torrent`，对《切尔诺贝利》2019 第一季资源 `802792` 返回 `OK/magnet`，其磁力保留 10 个 tracker。元数据预检确认 `private=false`、E01–E05 全部存在，视频总计 `1930722989` 字节。受控单条提交到 115 后，info-hash `cbeb3aebda4f5b704a5a41ebe2d57b1d7fd24183` 的离线任务显示已完成、100%，`/Media/TV_Show/Chernobyl.2019.S01.COMPLETE.1080p.AMZN.WEBRip.x265-PGW` 下五个 MKV 的总字节数完全一致。本次验证的是直接磁力和剧集目录路由；这部剧作为测试样本，不是片单质量选源的最终选择。

完整原因、实站结果及登录依赖见 [索引与下载冒烟记录](docs/index-download-smoke-2026-09-30.md)。

## 公网选源与 115 路由（v1.3.0）

新增的统一选源按质量档比较 Mini4K 与 M-Team：2160p Remux、1080p Remux、BluRay 编码、WEB-DL。对同档资源只比较已核实的 MKV/MP4 视频字节数；差距超过 `near_size_ratio`（默认 10%）时选较大者，相近时选公网。公网 CF／登录／解析故障保留暂停状态，不当作无结果。公网胜出后，只将已核实 `private=false` 且有完整文件清单的公开 BT 送 115；115 分享另有独立开关。

**目录对应关系：**电影的 115 离线下载和分享转存目标为 `/Media/Movie`，剧集为 `/Media/TV_Show`；两者必须是已存在的 115 网盘目录。任务完成后调用现有 P115StrmHelper 的 STRM 生成接口，把链接写到本地 `/Media/115_strm/Movie` 或 `/Media/115_strm/TV_Show`。片单只在 MoviePilot 媒体服务器确认电影或目标完整剧集季入库后写回 `downloaded=true`。

`public_selection_enabled` 初始关闭，片单继续使用原 M-Team 选源链路；公共宿主的 `public_only` 开启时覆盖这个业务开关，自动选源只查询公网，不回退 PT。正式提交须先启用公共宿主。公网 BT 默认路由 115，`p115_route_enabled` 默认开启；`share_115_enabled` 独立管理且默认关闭。旧配置中显式的关闭值仍保留。已有 PT 任务的恢复和回写不受 `public_only` 影响。磁力元数据预检使用固定版本 `libtorrent==2.0.15`，本机容器装在持久目录 `/config/filmwatchlist-deps`，只取 torrent metadata，不下载视频块。升级或迁移容器时需保留该目录，或重新安装依赖。
