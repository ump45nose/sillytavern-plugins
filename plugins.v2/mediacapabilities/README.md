# MediaCapabilities · 公共媒体获取宿主

独立 MoviePilot 插件，默认关闭。宿主只维护配置、受保护的 HTTP 接口、运行时
生命周期和公共提交记录；搜索、策略、预检与 adapter 实现在共享 wheel 中。

先在 MoviePilot 的 Python 环境安装 `media-capabilities[acquisition]` **0.3.3**，
再通过仓库根目录的插件清单安装 `MediaCapabilities` **0.1.2**。已有实例升级
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

Mini4K 完全使用 NAS 已有持久浏览器。首次登录或会话失效后，在 NAS 终端运行：

```sh
docker exec -it moviepilot /opt/venv/bin/python -m media_capabilities.acquisition.mini4k_login
```

账号由终端输入，密码隐藏输入且不保存。登录命令与 API 共用会话文件锁；
命令关闭浏览器后重新读取真实种子／磁力，确认保存的登录能够获取资源。
无须保持终端或用户桌面浏览器打开。仅核验现有会话可追加 `--verify-only`。
自定义会话目录时通过 `--profile-dir` 指定插件中相同的浏览器会话目录。
登录失效返回 `AUTH_REQUIRED`；Cloudflare 未完成返回 `CF_CHALLENGE`。

完整规则及迁移顺序见 [部署与架构](../../docs/media-acquisition.md)。
