# Mini4K 索引与 115 下载冒烟（2026-09-30）

## 原因与修复

- `AUTH_REQUIRED` 的实站证据是下载按钮指向 `/user/login`。CF 验证通过与 Mini4K 登录是两个条件；Linux 匿名会话不共享 Mac Chrome 的主站登录。
- 旧 Linux transport 使用 headless shell，直接读验证页。现复用 MoviePilot 已有 CloakBrowser、Xvfb 和独立持久配置，实际识别验证 iframe 中的 checkbox，输入后重新核对最终页面。实测主站验证通过，关闭并重开浏览器后仍可访问资源页；该 Linux 会话仍未登录。
- Relay 的 focus/click 返回 completed 时，Chrome 可能仍报告 background=true。现先核实标签可见，定位最新控件，点击后确认页面离开 CF 挑战；不会把操作完成误认为过盾。
- `.io` 与 `.com` 的登录互不共享；下载解析复用已核实的主站会话与最终重定向域名。失败响应分别给出 Linux 与 Relay 状态。主页健康不能覆盖最近解析失败。
- 直接磁力的 tracker 参数包含重复 HTML 转义。现先规范化磁力，再保留实际 tracker 取元数据和提交，避免丢失 tracker 后预检超时。

## 运行结果

运行中的 FilmWatchlist v1.3.1 已更新并重新加载，未开启批量公网自动下载。

| 检查 | 结果 |
| --- | --- |
| Linux 主站 CF 验证 | 自动定位控件并通过，最终打开资源 802792；无需人工勾选 |
| Linux 主站登录 | 未登录；下载按钮要求登录，正确归类 AUTH_REQUIRED |
| 运行 API 解析资源 802792 | HTTP 200，OK，真实 magnet，10 个 tracker |
| 运行 API 解析资源 962326 | HTTP 200，OK，实际 torrent，4 个文件，private=false |
| 运行 API 健康状态 | 总体、page_status、resolve_status 均 OK |
| 直接磁力元数据 | private=false，18 个文件，5 个 MKV，S01E01–S01E05 |
| 115 目标路径 | /Media/TV_Show |
| 115 离线任务 | status=2，percentDone=100，目标目录正确 |
| 115 实际文件 | 五个 MKV，视频总字节数 1930722989，与磁力元数据完全一致 |

剧集样本：`Chernobyl.2019.S01.COMPLETE.1080p.AMZN.WEBRip.x265-PGW`，来源资源 `802792`，info-hash `cbeb3aebda4f5b704a5a41ebe2d57b1d7fd24183`。实际云端目录：`/Media/TV_Show/Chernobyl.2019.S01.COMPLETE.1080p.AMZN.WEBRip.x265-PGW`。只提交一次；样本用于验证直接磁力和剧集目录路由，不代表质量选源的最终选择。未改片单 downloaded 状态。

受保护下载目前仍使用已登录的 Chrome 后备会话，不能将这次验证表述为 Linux 已完成独立登录。Linux 会话通过 CF 后如需独立解析受保护链接，必须先初始化该独立配置的 Mini4K 登录状态。CF 后续可能再出现，无法自动完成时仍返回 CF_CHALLENGE；没有保证所有挑战都可自动通过。

基本验证包括源码编译、索引冒烟、Relay 会话/域名/下载冒烟和上述实站链路；没有扩大回归测试。
