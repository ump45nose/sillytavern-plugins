# MCP 名称查询兜底验收 · 2026-10-05

当 MoviePilot 媒体识别无结果或服务异常时，公共搜索改为按调用方提供的名称和可选年份
直接查询 M-Team、Mini4K。未指定媒体类型时查询不限定为电影；已返回多个身份或模糊
身份时仍保留 `needs_selection` 消歧流程。只有 ID、没有名称的请求无法进行名称兜底。

结果附带 `identity_status=unverified` 和 `warnings`，不伪造 TMDB/IMDb ID 或季集清单。
这层兜底只用于查询；下载仍要求确认媒体身份，兜底候选引用不能跳过此核验。
同时修复 Mini4K 双语标题拆分时丢失英文片名的问题，以及 M-Team 未知身份查询的 ID 过滤。

## 部署

- 共享包升级至 **0.3.2**，MoviePilot 使用 `/config/media-capabilities-runtime/0.3.2`。
- MCP 业务后端升级至 **0.1.2**，镜像 `local/media-download-mcp:0.1.2-fallback`。
- MediaCapabilities **0.1.1**、FilmWatchlist **1.4.3** 插件代码保持原版本。
- 网页 API、三个 MCP 工具的名称和参数结构保持不变；应用共享包依赖锁同步至 0.3.2。
- 原公网 MCP 地址、OAuth 注册、访问令牌、浏览器会话及下载路由配置保留。
- 更新期间暂停新提交，重启后原配置恢复；原 6 条资源登记和 8 个任务保留。
- 备份位于 MoviePilot 配置目录的 `backups/search-fallback-20261005T021854Z`。

## 基本验证

只运行新增的名称兜底冒烟和既有获取链路基本冒烟，没有执行大量回归。
已覆盖两站名称查询、元数据无结果／异常、双语标题、年份过滤、分页、MCP 调用、
消歧保留以及未核实身份的下载拦截。

通过现有公网 MCP 网关的回环入口完成工具发现和真实 `search_resources` 调用：

```json
{"request": {"title": "Big Buck Bunny", "year": 2008}}
```

最终返回 `status=complete`、`identity_status=unverified`，两站均为 `OK`：

| 站点 | 首批候选 | 耗时 |
|---|---|---|
| M-Team | `Big Buck Bunny 2008 WEB-DL 2250p HFR H.264 AAC 5.1-Jerold` | 3.7 秒 |
| Mini4K | `big_buck_bunny_720p_surround avi` | 36.6 秒 |

首批结果在 3.7 秒返回，Mini4K 随后完成；本次没有调用 `download_media`，没有新增下载。
Mini4K 返回的 AVI 候选可以展示，但下载仍受既有 MKV/MP4 格式规则限制。
私有部署摘要和只读查询结果保存在 `.build/search-fallback-20261005/`，不含访问令牌。
