# 媒体工具部署与验收 — 2026-10-03 至 10-04

## 部署范围

复用 NAS 的 MoviePilot 2.14.2 容器、`/config/local-plugins` 本地安装机制和插件数据表。
新增 MediaArchive、DiscRemux 及 media-capabilities wheel，没有增加常驻服务或数据库。
Emby API token 保存为权限 0600 的服务端文件，下载器连接复用 MoviePilot。

- 原盘目标：`/Media/Movie/动画电影/福音战士新剧场版：序 (2007)/福音战士新剧场版：序 (2007).iso`。
- 归档目标：Emby 本地电影 157887，TMDB 1280738《火遮眼》；所选用户 sfw。
- 归档种子：qBit / `f4ae226a8ed0c40f12ab9b167e868484e647e75b`，M-Team。
- 保种统计：42.3 天、分享率 0.64776，满足 30 天或 1x；未触发 30 天内 2x 保留分支。
- 原盘 44,238,372,864 字节；归档源 72,424,930,386 字节。

## 兼容性修复

- 保留 MoviePilot 版本检查。P115Disk 最新版要求 >=2.15.2，部署使用其官方
  `P115Disk_v0.2.27` 发布包（SHA256 `2a8e69e768fd58fee1c20fd50401831637e76bc66ebe4194ed94feb67c7689d6`），
  通过本地插件机制安装，复用已有 115 客户端。
- MakeMKV 2.0.0 打开该 ISO 后发生 SIGSEGV，官方 1.18.4 可读取 24 个标题并转换。
  运行工具及 wrapper 保存在 `/config/discremux-runtime`；beta key 有效期须维护。
  本次使用的 [官方 beta key 公告](https://forum.makemkv.com/forum/viewtopic.php?t=1053)
  有效至 2026 年 10 月末，届时更新 key 或配置正式授权。
- 页面增加单作品处理，保留完整基线；列表读取不触发完整季外部识别。
- 清理时启用但无法访问的 qB 不能被略过，未知引用关系必须禁止清理。
- REMUX 只要求保留实际源字幕，排除空的虚拟 forced-only 派生轨道数量。
- Emby 4.10.0.40 的刷新接口不接受 `ImageRefreshMode=None`（服务端返回 400），
  使用 `Default`，保留图片与已有元数据；插件等待异步刷新后自行核对标识和迁移状态。
  [官方刷新接口参数](https://dev.emby.media/reference/RestAPI/ItemRefreshService/postItemsByIdRefresh.html)。
- Emby 把新归档版本合并进已有《火遮眼》条目，用户枚举省略副版本。
  适配器改为核对确切 STRM 路径，再核对副版本自己的媒体源 ID 是否出现在该用户
  可见条目中；任务保存 `library_targets` 归属回执。没有扩大用户媒体库权限。

## 验收

Chrome 中的 MoviePilot 页面通过 Browser Relay 调试。两项任务均从页面单独提交。
验收依据为插件任务状态和回执，媒体校验、状态写入及清理由插件执行。

### DiscRemux：通过

2026-10-04 00:00（Asia/Taipei）读取到第 2 次执行 `DONE`。
插件重新读取原盘，自动选中标题 0（6057 秒、33 章节），重新转换、验证媒体流和章节、
计算完整 SHA1，再提交到独立产物目录。`delete_original=false`，保留原 ISO。

- 产物：`/Media/Remux/福音战士新剧场版：序 (2007)-4f20f8e63e-r2/福音战士新剧场版：序 (2007).mkv`。
- 大小：30,928,470,626 字节。
- SHA1：`5E97914D3ECDD3131CF6E3D52AECC66793DCFCE0`，由插件计算。
- 任务读取记录：`.build/acceptance/discremux-plugin-result.json`。

此前第 1 次执行在字幕计数修复过程中由操作者手工补写过转换检查点，
该次结果不计入验收。第 2 次使用 `attempt-2` 临时目录，不读取第 1 次检查点，
也未手工推进阶段、创建回执或调用外部工具替代插件验证。

### MediaArchive：通过

2026-10-04 00:54（Asia/Taipei）插件返回 `DONE`，`cleanup.complete=true`。
恢复任务使用 MoviePilot 原生插件运行接口与已有服务令牌；整个流程由原插件后台队列执行。
未手工更新任务阶段、填入云端/迁移/清理回执，未单独调用媒体库写入或下载器删除接口。

- 普通 MKV 已上传到 115，插件回查云端 ID、72,424,930,386 字节大小和 SHA1
  `EBACDAD66243443D61BA4A69F378448912390909`。
- STRM：`/Media/115_strm/Movie/17b6abbc25974bb0df08/The Furious 2025 Hybrid 2160p UHD Blu-ray Remux DoVi HDR10+ HEVC TrueHD 7.1 Atmos.strm`。
  链接读取与 FFprobe 探测均由插件执行，恢复状态迁移前及清理前再次验证。
- 新版本 167220 属于用户可见条目 162368 的版本组，归属记入 `library_targets`。
- 所选用户 sfw 的 `Played=true`、`IsFavorite=true` 已读取确认，
  从源条目 157887 到新版本 167220 的确认记入 `migration_receipts`。
  Emby 版本组原有状态已一致，插件采用幂等确认。
- 插件保存 qBit 种子删除意图，删除后回查确认，再删除上述源 MKV；
  清理回执 `removed` 有 1 个文件，`retained` 为空。
- 任务读取记录：`.build/acceptance/mediaarchive-plugin-result.json`。

真实验收覆盖指定的两个电影样本。完整季、保种等待、高分享率保留、歧义转人工和失败不清理
使用假适配器进行基本冒烟检查，没有扩大真实媒体处理范围。

归档任务：`17b6abbc25974bb0df08bfe7c0a3e529437843676ad60febe75aef1aa2ebebe0`。
REMUX 任务：`4f20f8e63e5a7564e011b7c9d73f9ebb0f6ad761c0af5a5024f791a39ec96ea4`。

## 基本检查

5 项冒烟检查通过；布局契约、业务层导入边界、Vue 构建、wheel 构建和 `git diff --check`
通过。未扩展大规模回归测试。

## 部署持久化

- 本地镜像：`local/moviepilot-media-tools:2.14.2-20261003`。
- 镜像 ID：`sha256:550be99e0a083cea265b00f5b224a0800630612606c4509e86f18e295f5878ed`。
- wheel SHA256：`4e58c658d30614e6aa7dbd6223b1bd3857fc134c3b475c951eb7d6826f9d9dd2`。
- 现有 Compose 仅修改 MoviePilot 镜像；备份为
  `/vol2/1000/Docker/stacks/media/compose.yaml.before-media-tools-20261003234657`。
- 已通过 Compose 重建 MoviePilot；公共包、刷新修复、MakeMKV wrapper 与
  DiscRemux 第 2 次 `DONE` 记录及 SHA1 均保留。容器健康检查通过。
- `/config` 和媒体目录沿用已有挂载。Emby、qB、115 及 Theme Worker 使用已有服务。
- 最终两个插件均启用、无配置错误、队列空闲，两个作业均为 `DONE`。
- 日常归档恢复 `dry_run=true`、`cleanup_enabled=false`、`backfill=false`，
  每日 03:00 使用 MoviePilot `Asia/Shanghai` 时区（与 Asia/Taipei 同为 UTC+8）；
  DiscRemux 保持 `delete_original=false`。
