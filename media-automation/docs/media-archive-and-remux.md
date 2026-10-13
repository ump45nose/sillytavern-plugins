# 收藏归档与独立 REMUX

`MediaArchive` 和 `DiscRemux` 是两个独立的 MoviePilot V2 插件，共用可单独构建的
`media-capabilities` Python 包。首版默认关闭；收藏归档默认预览，两个插件的清理开关均默认关闭。

## 代码边界

- `plugins.v2/mediaarchive/workflow.py`：收藏基线、完整季、保种策略、阶段恢复和归档编排。
- `plugins.v2/discremux/workflow.py`：分析、自动/人工选择、转换、产物提交和独立任务恢复。
- `packages/media-capabilities/src/media_capabilities`：数据类型、能力接口、纯策略，以及文件、
  Emby、MoviePilot/qB、P115、MakeMKV 适配器。适配器按需导入宿主依赖。
- `frontends/media-tools`：共享页面源码，分别构建两个插件的 Module Federation 分发文件。

业务工作流不直接访问 HTTP、文件系统、MoviePilot 或子进程。宿主入口组装能力。
上传只返回云端文件回执；REMUX 只交付文件；媒体库扫描和 `Played/IsFavorite` 迁移由
`EmbyLibrary` 实现。各插件分别使用 MoviePilot 插件数据存储，没有新增数据库或常驻服务。

归档流程：

```text
CHECKING → SEED_WAIT / PREVIEW → PREPARING → UPLOADING → CLOUD_VERIFY
         → STRM_VERIFY → MIGRATING → CLEANING → DONE
```

REMUX 流程：

```text
ANALYZING → MANUAL / CONVERTING → COMMITTING → CLEANING → DONE
                         失败 → FAILED（保存原阶段，可人工重试）
```

## 构建与安装

MoviePilot 安装单个插件只复制其插件目录，不能从相邻源码目录导入共享包。
先在目标 MoviePilot 的 Python 环境中安装共享 wheel，再安装两个插件：

```sh
python3 -m pip wheel --no-deps --wheel-dir .build/wheels ./packages/media-capabilities
# 在 MoviePilot 容器/解释器中执行；路径替换为已复制的 wheel：
python3 -m pip install /path/to/media_capabilities-0.1.0-py3-none-any.whl
cd frontends/media-tools
npm ci
npm run build
```

根 `package.v2.json` 已注册 `MediaArchive` 和 `DiscRemux`。预构建页面位于各插件 `dist`。
使用已有本地插件仓库安装机制即可，不需要另建插件服务。

运行归档需要：

- MoviePilot 中已有启用的 qB 下载器；复用宿主连接，不另保存 qB 密码。
- 已登录的 P115StrmHelper，以及它的上传实现依赖的 P115Disk 插件。
  上传适配器使用 `P115DiskCore`；安装版缺少这些接口时任务暂停。
- Emby 地址、选定用户，以及保存 API token 的服务端文件。
- MoviePilot、qB 和 Emby 的路径能映射到插件可读取的文件；首版支持普通文件、目录及硬链接，
  符号链接输入会保留并暂停处理。
- FFprobe。原盘任务另需可执行的 `makemkvcon`；插件不会自动安装工具或配置授权。

FilmWatchlist 在共享包可用时复用其云文件查询与 STRM 生成；尚未安装 wheel 的已有部署
继续使用原有兼容实现。新插件不依赖 FilmWatchlist 或 Theme Worker 的安装状态。

## 配置与页面

手动处理单个作品时先点击“读取收藏作品”，选择作品，再点击“仅处理所选收藏”。
该操作只恢复或提交所选作品，首次仍记录完整收藏基线，避免其他已有收藏被误当作新增。
收藏列表不请求外部剧集信息；提交目标剧集时才核实完整季。


侧栏“媒体收藏归档”支持设置、用户多选、立即扫描、补处理、仅处理所选收藏和任务详情；
“原盘 REMUX”支持浏览允许目录、选择 ISO/BDMV、自动处理、人工选片、集序指定和失败重试。
独立任务终止后可点击“重新分析并转换”，创建新的执行次数并从原盘开始。旧结果保存在
任务历史中；临时目录按执行次数隔离，原地输出的后续执行使用带任务 ID 和执行次数的文件名，
独立输出目录按执行次数隔离，不复用旧转换回执，也不覆盖旧产物。
归档持有的 REMUX 作业只能按原阶段恢复，避免改变归档已引用的产物。

归档的媒体库模块将源媒体已确认的标识发布到 STRM 同目录 NFO，随后安排 Emby 刷新。
已有无标识 NFO 会保留其他元数据并补入标识；标识冲突、集序冲突或并发修改时暂停。
Emby 合并电影版本时，插件仍核对新 STRM 的确切路径，并确认它的媒体源 ID 属于
所选用户可见条目，再迁移状态；不能仅按作品名称或 TMDB ID 认领已有版本。

归档主要配置：

| 配置 | 默认 / 含义 |
| --- | --- |
| `enabled` / `dry_run` | `false` / `true` |
| `cron` | `0 3 * * *`，使用宿主 `settings.TZ` |
| `users` | Emby user ID 列表，任一用户收藏即可触发 |
| `emby_token_path` | `/config/mediaarchive-emby.token`，不把 token 写进配置或作业 |
| `source_roots` | `["/Media"]` |
| `movie_path` / `tv_path` | `/Media/Movie` / `/Media/TV_Show` |
| `strm_root` | `/Media/115_strm`，应属于 Emby 可扫描的媒体库 |
| `remux_output_dir` | `/Media/Remux`，归档额外允许读取的 REMUX 目录；原地产物在 `source_roots` 内，无需修改 |
| `seed_rule` | `{"days":30,"ratio":1,"mode":"any"}`；`all` 表示同时满足 |
| `high_ratio` / `high_days` | `2` / `30`，观察窗口内达标后永久保留做种 |
| `backfill` | `false`，首次成功扫描建立每个选定用户的历史收藏基线 |
| `cleanup_enabled` | `false`，归档验证完成后停在等待清理，可配置启用 |

站点规则可按历史中的站点名或 tracker 域名覆盖：

```json
{"tracker.example":{"days":30,"ratio":1,"mode":"all"}}
```

规则优先级：显式站点覆盖、MoviePilot 下载历史 `note.seed_rule` 的可确认规范化规则、全局默认。
不同站点的保种要求没有统一的 MoviePilot 字段；适配器不把 qB 自动停止条件当作站点要求。
来源关联、tracker 归属或实际统计无法确认时保留。

路径映射按最长前缀匹配：

```json
{"path_mappings":[{"emby":"/media","local":"/Media"}],
 "downloader_path_mappings":[{"downloader":"/downloads","local":"/Media/Downloads"}]}
```

DiscRemux 的 `path_mappings` 使用 `downloader/local` 格式，服务于原盘删除检查。
该插件支持 `source_roots`、`output_dir`、`delete_original`、`makemkvcon`、`ffprobe` 和超时设置。
`output_dir` 默认留空，表示原地处理：ISO 的 MKV 与 ISO 同目录；选择包含 BDMV 的原盘
文件夹或其中的 BDMV 时，MKV 放在原盘文件夹内，与 BDMV 并列，不创建作品/任务子文件夹。
例如 `/Media/Downloads/Movie/Film.iso` 输出为 `/Media/Downloads/Movie/Film.mkv`。
转换临时文件和恢复回执位于同一目录下的 `.discremux/<任务 ID>`，不纳入原盘清单或清理。
显式填写 `output_dir` 时仍输出到该目录下的作品/任务子文件夹；已有配置和已提交任务保留
原路径。已有部署可在设置中清空“REMUX 产物保存目录”，让后续新任务原地输出。
归档提交的 REMUX 任务强制保留原盘，独立任务按本插件配置处理。

## 自动判断和产物

电影：已有参考时长时允许误差为 3 分钟或 5%（取较大者）；没有参考时长时排除不足
20 分钟的标题。只有一个候选组才自动选择；章节/大小用于候选排序，不能裁决多剪辑版。
相同片段序列和时长的播放列表合并，选轨道信息最完整的候选。
剧集：必须有明确标题到集序映射；单集原盘可使用已确认的集序与唯一主片。
其他剧集原盘在页面人工指定集序，不根据播放列表编号猜测。

MakeMKV 使用直接复制输出配置。产物时长与所选标题核对，FFprobe 核实视频流，计算 SHA1；
同输出卷内用原子硬链接提交，不覆盖不同内容的同名文件。任务目录保留转换回执供恢复使用。
页面交付产物路径，不生成 NFO/图片、不调用媒体库。

## 验证与清理

上传前保存意图，云端按任务目录、名称、大小和 SHA1 对账；丢失响应或重启后查不到
文件不会自动重传。页面的人工重试会先重新查询云端，再明确释放未确认的提交意图。
STRM 生成关闭插件隐式媒体刷新，并保存文件归属和内容摘要；播放检查使用有界 HTTP
读取及 FFprobe，不上报播放会话或修改已看状态。

媒体库按实际 STRM 路径、provider ID、季和集序定位目标，迁移每个选定用户的
`Played/IsFavorite` 并回读验证。扫描异步，目标尚未入库时等待下一次运行。
缺少完整季元数据、目标 provider ID 或唯一文件关联时任务保留；首版不凭标题猜测身份。

清理前重新核对云端、STRM、用户状态、种子规则和文件身份。qB 先删除任务、
`delete_files=false`，确认后只删除已核实文件；共享、交叉做种、未知硬链接或整包包含
未归档文件时保留。删除意图在调用下载器前持久化，允许部分清理后恢复。
高分享率写入 `MediaArchive_KEEP` 标签和任务记录，完成后不再重复扫描。
其他下载器清理插件应把该标签配置为排除项；本插件的保留策略不改写其配置。

独立 REMUX 原盘删除只允许产物全部验证、没有任何 qB 文件引用且没有未知硬链接的来源。
无法查询下载器时保留原盘。已生成产物不等于可以解除保种要求。

## 基本冒烟

```sh
PYTHONPATH=packages/media-capabilities/src python3 tests/smoke_media_archive.py
python3 tools/check_layout.py
```

该小套件使用临时文件和假外部服务，覆盖电影/完整季、丢失上传响应后恢复、保种与保留、
失败不清理、REMUX 歧义/人工选择及本机 FFmpeg/FFprobe 小视频样本。
它不冒充实际 Emby/qB/115 或 MakeMKV 原盘验收。实接时先保持预览，使用一部指定电影；
确认源文件与种子关联后上传单条，再核对 STRM、状态迁移，最后启用清理。

参考实现：[ARM](https://github.com/automatic-ripping-machine/automatic-ripping-machine/blob/main/arm/ripper/makemkv.py)、
[MakeMKV CLI](https://www.makemkv.com/developers/usage.txt)、
[P115DiskCore](https://github.com/DDSRem-Dev/MoviePilot-Plugins/blob/main/plugins.v2/p115strmhelper/core/p115disk.py)。

### 引擎与依赖版本

真实部署记录见 [媒体工具验收](media-tools-acceptance-2026-10-03.md)。该实例 MoviePilot 为
2.14.2，使用兼容的 P115Disk 0.2.27 发布包；新版存储插件的宿主版本约束必须正常检查。
MakeMKV 2.0.0 在受控 ISO 上崩溃，实例使用官方 1.18.4。MakeMKV 的 beta 授权有时限，
需要在到期前更新授权或使用正式授权，不在代码中保存授权字符串。

MakeMKV 会列出从完整字幕生成的虚拟“仅强制字幕”轨道。验证必须保留完整源字幕，
允许没有字幕帧的虚拟过滤轨道不出现在产物中。转换命令成功后的文件快照单独落盘，
验证阶段重试可复用已确认完成的转换，继续计算校验值和提交文件。

### 原地输出更新 — 2026-10-07

DiscRemux 0.1.1 配合共享包 0.3.4，默认 `output_dir=""`。NAS 已安装共享包至
`/config/media-capabilities-runtime/0.3.4`，插件运行副本使用持久化的
`/config/plugin-runtime/discremux` 挂载，本地安装源和清单同步更新。
现有插件的输出目录清空，`delete_original=false` 保持不变；原有任务继续使用冻结路径。

9 项新测试覆盖 ISO、原盘文件夹、BDMV、允许目录根、重复提交、重新转换、旧任务恢复、
同名文件冲突、剧集命名及原盘清理；原有 5 项媒体工具冒烟通过，前端和 wheel 构建通过。
全量离线测试为 48 通过、9 失败；相同 9 项在修改前代码中复现，涉及已有的 P115 测试
桩缺失 `StrmApiStatusCode`、选择模块冒烟接口及 FilmWatchlist 工作流冒烟，未纳入本次修改。
