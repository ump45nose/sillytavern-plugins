# MediaCapabilities · 公共媒体获取宿主

独立 MoviePilot 插件，默认关闭。宿主只维护配置、受保护的 HTTP 接口、运行时
生命周期和公共提交记录；搜索、策略、预检与 adapter 实现在共享 wheel 中。

先在 MoviePilot 的 Python 环境安装 `media-capabilities[acquisition]` **0.3.2**，
再通过仓库根目录的插件清单安装 `MediaCapabilities` **0.1.1**。已有实例升级
共享包后需重启 MoviePilot。打开“启用公共获取宿主”，按需要配置站点与 115 路由。
查询网页和下载 MCP 可以在 FilmWatchlist 未安装时使用。

五个 Bearer 接口位于 `/api/v1/plugin/MediaCapabilities/acquisition_*`。
FilmWatchlist **1.4.2** 通过插件管理器取得同一个运行时，不使用本机 HTTP 回环。
公共配置及 `acquisition_v1` 记录由本插件保存，片单业务记录仍归 FilmWatchlist。

首次初始化补充读取旧配置和提交记录，保留原数据、已有新配置、任务 ID 和历史
浏览器会话路径。安装迁移期间先暂停旧片单新提交，接入完成后再恢复扫描。
公共宿主停用时暂停新提交，已有回执可继续读取；仍要求单个 API 工作进程。

`public_only` 默认关闭，只限制新的自动选源；开启后 MCP／网页和片单只选公网，
手动指定 PT 不受限制。公网 BT 默认通过 115，路由开关默认开启；115 分享开关独立且默认关闭。

使用 Browser Relay 时，在远端 Chrome 保留一个已登录的 Mini4K 标签。宿主复用该标签，
设备 ID 从受保护文件读取；更换设备无需在网页或 MCP 保存浏览器凭据。

完整规则及迁移顺序见 [部署与架构](../../docs/media-acquisition.md)。
