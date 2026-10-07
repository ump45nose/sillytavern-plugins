# 通用洗版检测与 Adult 收藏

## 目标

本实现把“候选获取”和“是否值得洗版”分开：

- 普通媒体只做只读洗版检测，不自动下载、不删除当前版本。
- Adult 收藏按 Emby `liked/favorite` 驱动。
- Vixen 与 JAV 使用独立策略，避免把影视质量规则硬套到发行命名不稳定的 Adult 资源。
- 文件迁移、下载来源和媒体状态恢复都复用现有 `media-capabilities` 能力。

## 通用媒体洗版检测

`MediaCapabilities` 新增：`POST /acquisition_upgrade_check`。

输入沿用 acquisition 请求，并额外携带当前版本事实：`current.title`、`current.video_bytes`、可选 `current.probe`（ffprobe JSON）。

检测流程：身份识别 → 现有 M-Team / Mini4K source adapter 查询 → torrent / magnet 元数据核验 → 复用 `quality_key` / `MediaCandidate.tier` 比较 → 返回 `keep / upgrade / unknown`。整个接口只读，不提交下载。

同档资源继续使用 `near_size_ratio`，普通媒体不会出现第二套互相打架的质量评分。

## AdultCollection

默认关闭，且 `dry_run=true`。默认 JAV 目录 `/Adult/JAV`，Western 目录 `/Adult/Western`，对应收藏目录为各自根目录下的 `Collection`。

### Vixen

仅处理 Emby 收藏项。文件必须属于 Western 媒体库，标题、路径或 Emby Studio 命中 Vixen，且 ffprobe 实际分辨率达到 2160p。无法取得 probe 时才回退文件名质量标记。满足后迁移到 `/Adult/Western/Collection`，保留原相对目录结构。

### JAV

仅处理 Emby 收藏项。文件必须属于 JAV 媒体库，且标题或路径可提取有效番号。M-Team 与 JavDB 两边都至少取得一个已核实候选后才作结论。

比较策略只使用可稳定获得的事实：分辨率优先，同分辨率比较视频文件体积，差异不超过 `near_size_ratio` 视为接近。

只有 M-Team 与 JavDB 两边都判断当前版本足够接近时，才迁移到 `/Adult/JAV/Collection`。任一来源不可用、无结果或候选无法核实都会进入 `WAIT_SOURCE`，不会把“搜不到”错误解释成“当前已经最好”。

若发现更优版本则进入 `NEEDS_UPGRADE`。开启 `auto_upgrade` 后才会提交替换资源：M-Team 复用 MoviePilot 下载器；JavDB 公网磁力仅在 `public_route_enabled=true` 时复用 P115 离线任务。替换资源提交后保留当前文件，本版本不会在新资源尚未验证进入媒体库前删除旧文件。

## JavDB

JavDB 不直接维护 HTML 爬虫。适配器调用外部 `javdb-cli` 的 JSON 接口，只消费番号、info hash、大小和磁力等稳定字段。

推荐固定使用 `javdb-cli v0.8.2` 或经过测试的兼容版本，并通过 `javdb_binary` 指向可执行文件。插件不会自动下载或更新该二进制。

JavDB 返回的磁力仍会经过项目现有 `magnet_evidence` 二次核验；私有种、无法取元数据的磁力不会参与归档判定。

## 迁移安全

实际文件迁移前调用现有 `MoviePilotDownloader.deletion_allowed`。文件仍被下载器引用、存在额外硬链接，或下载器状态无法确认时都不移动。

迁移使用 `LocalFiles.relocate`：同卷原子 rename；跨卷先复制并 SHA-1 校验，再原子落盘并删除源；不覆盖不同内容的既有文件。

迁移前记录每个配置用户的 Emby 已看/收藏状态。迁移后等待 Emby 扫描目标路径，写回并回读确认状态；中途失败会保留 `MIGRATION_PENDING`，下一次任务继续恢复。

## 运行建议

首次部署保持 `dry_run=true`、`auto_upgrade=false`、`public_route_enabled=false`。确认路径映射、Vixen 识别、JAV 番号和候选质量判断后，再逐项开启写操作。
