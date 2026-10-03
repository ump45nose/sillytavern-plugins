# FilmWatchlist：质量选源与 115 任务路由详细设计

状态：v1.3.0 已实现核心链路；新选源和 115 提交开关默认关闭，仍需按文末顺序做单条真实任务验收。当前生产配置未切换，定时扫描仍只向 M-Team 下载器提交任务。

## 目标与约束

- 对 Favsync 的一条媒体记录，同时取得 Mini4K 和 M-Team 的候选，完成同一套身份、格式和质量核验后再提交一个任务。第一批来源固定为 Mini4K 与 M-Team；不修改 MoviePilot 的全局订阅和其他下载任务。
- 保持既有偏好：2160p Remux、1080p Remux 优先；排除 ISO、BDMV、原盘和无可核实 MKV/MP4 文件的资源。剧集要求目标季集数可核实且完整。
- 同一分辨率、同一片源档内，先比较**可播放视频文件的总字节数**。差距超过阈值时取较大的；相近时优先公网。阈值建议默认为较大值的 10%，作为插件配置项，不写死在索引器里。
- 公网只允许已核实为公开 BT 的磁力／种子进入 115 离线，115 分享走分享转存。PT 继续走 MoviePilot 原有下载器，不把 PT 链接送到 115。
- `downloaded=true` 的业务含义仍是电影已在媒体服务器入库，或目标剧集季完整入库。任务受理、115 离线完成、STRM 生成均是中间状态。

## 现有能力与缺口

| 部件 | 当前可复用能力 | 新阶段必须补齐 |
| --- | --- | --- |
| FilmWatchlist | Favsync 分页、媒体识别及国家／年份过滤、M-Team 搜索、种子文件检查、下载历史去重、媒体库核验、片单写回 | 双来源候选汇合、统一裁决、持久任务状态和 115 路由 |
| `PublicIndexer` | `search / resolve / health`；Mini4K 的电影／资源页与磁力、种子、网盘链接证据 | 对候选补充可播放文件大小；磁力元数据预检；115 分享文件预检 |
| P115StrmHelper | `add_offline_task`、`offline_tasks`、`add_transfer_share`、云盘整理和 STRM 代码 | 适配其接口返回值，按 info-hash 对账；重启后补整理；受控的分享链接提交 |

实测安装版 P115StrmHelper 的离线提交只返回新增数量，不返回任务 ID；`offline_tasks` 可返回 `info_hash`、进度和状态，且列表有约 120 秒缓存。其自动整理待处理列表 `transfer_list` 是进程内存；重启可能丢失，且使用显式下载路径时不加入这个列表。FilmWatchlist 不能把 API 的“添加成功”当作“下载并整理完成”。

## 模块接口

在 `plugins.v2/filmwatchlist` 中新增以下模块；`PublicIndexer` 继续只负责索引，不做排序或入队。

```python
class EvidenceCollector(Protocol):
    def collect_public(self, query: MediaQuery) -> SourceBatch: ...
    def collect_pt(self, mediainfo, site_id: int) -> SourceBatch: ...
    def preflight(self, candidate: UnifiedCandidate, expected_episodes: set[int] | None) -> CandidateEvidence: ...

class QualitySelector(Protocol):
    def choose(self, query: MediaQuery, batches: list[SourceBatch],
               expected_episodes: set[int] | None) -> SelectionDecision: ...

class TaskRouter(Protocol):
    def submit(self, decision: SelectionDecision, idempotency_key: str) -> SubmitResult: ...
    def reconcile(self, task: AcquisitionTask) -> TaskObservation: ...
    def ensure_organized(self, task: AcquisitionTask) -> TaskObservation: ...
```

`UnifiedCandidate` 包含 `source_id`、`source_kind`（`PUBLIC_BT`、`PT`、`SHARE_115`）、`candidate_id`、媒体 ID、标题、片源、分辨率、标称大小、链接种类及原始索引证据。`CandidateEvidence` 再包含解析后的 info-hash／分享标识摘要、private 标志、文件名与逐文件大小、可播放视频总字节数、目标季集数、鉴权有效性、检查时间和拒绝原因。未知值保持 `None`；索引页报告的总大小不能冒充已核实的视频大小。完整链接和 115 提取码只在受保护的临时调用上下文存在，插件状态和日志只存摘要。

`SourceBatch` 返回候选和来源状态。搜索应并发执行并在统一截止时间内等待两方，不能因某一方先返回就提交。搜索分页上限沿用现有索引器的限制；超限是故障而非 `NO_RESULTS`。仅对入围候选做 `resolve`／文件预检，设候选数量与总耗时上限，避免把每条 Mini4K 资源页全部打开。

### 文件预检的补充

1. `.torrent`：解析原始 bencode，验证 info-hash、`private` 字段、路径和各文件长度；仍沿用 `inspect_files` 的格式和剧集覆盖检查。
2. 磁力：现有 `resolve` 通常只有 info-hash，没有文件清单或 private 标志。新增受时限约束的**元数据获取步骤**，只取 torrent metadata，不下载影片数据；核对获取的 info-hash 后解析文件清单和 private 标志。取不到 metadata 的候选记为 `EVIDENCE_MISSING`，不能自动送 115。
3. 115 分享：用已登录 115 客户端只读列出分享内容、文件大小、提取码有效性，核对可播放文件与目标季。不能只凭 Mini4K 页面写着“115”就转存。其他网盘分享仍为 `UNSUPPORTED_ROUTE`。
4. PT：复用 `DownloadChain.download_torrent` 获取种子与文件列表，再从种子取得逐文件大小。只预检有限数量的高档候选，不提前向下载器提交。

BT 元数据、文件清单和分享列表是路由的前置条件。Mini4K 目前实站取得的 Remux 磁力尚无文件清单，因此**仅有现有索引接口时不能直接启用 115 自动下载**。

## 裁决规则

先做硬过滤：媒体 ID／标题、年份、国家、类型、季号匹配；文件可播放；剧集完整；公网 BT `private == False`；链接未失效。标题质量标签用于初筛，最终以实际文件与媒体信息复核。容量异常或内容与标题明显不符的候选拒绝或标记待核实，不因“更大”自动胜出。

质量档从高到低：`2160p Remux → 1080p Remux → 2160p BluRay 编码 → 1080p BluRay 编码 → 2160p WEB-DL → 1080p WEB-DL → 其余已允许档`。先在每个来源的同档候选中取可播放视频字节数 `V` 最大的一个，再比较公网与 PT 的来源代表。若 `(Vmax - Vmin) / Vmax > near_size_ratio`，选较大者；否则选公网（包括可核实的 115 分享），再按 HDR／音轨、可用性和 PT 做种数稳定排序。这样多候选时也不会因两两“相近”造成非传递排序。大小未知的候选不参加自动同档裁决，先补证据；无法补证据则记录原因并尝试其他候选。跨档绝不因为体积大而升档。

裁决结果保存各候选的档位、视频大小、来源、拒绝原因和胜出理由；`non_remux` 只写入插件记录，不改片单数据。选择时对同一 info-hash 的重复链接合并，优先保留可走公网的证据。预览模式执行搜索与裁决但不调用任务路由。

| 公网结果 | PT 处理 |
| --- | --- |
| `OK` 且有合格候选 | 同档比较；若 PT 更优则照常选 PT |
| `NO_RESULTS` 或全部候选经确定性检查后不合格 | PT 兜底 |
| `AUTH_REQUIRED`、`CF_CHALLENGE`、`UNAVAILABLE`、`PARSE_CHANGED`、搜索超时 | 暂停该条并告警；不把“公网不可查询”误作“公网无资源” |
| 公网链接临时失效、元数据无法核实 | 试下一个公网候选；若仍无法证明公网无可用候选则标记待核实，避免无条件 PT 兜底 |

可配置的人工“本条允许 PT 兜底”覆盖长期公网故障，覆盖动作和操作者要留痕；默认不自动越过故障门槛。若 115 账号、空间、配额或服务异常，停止 115 路由并保留待处理决策，不批量切换 PT。

## 115 与 PT 路由

| 输入 | 提交方式 | 对账键 | 完成检查 |
| --- | --- | --- | --- |
| 已核实公网磁力 | P115StrmHelper `add_offline_task`，单链接提交 | info-hash | `offline_tasks` 状态 0/3 等待、1 失败、2 云端完成；再核对云端文件、整理和媒体库 |
| 已核实公开 `.torrent` 字节 | 仅在确认可构造等价公开磁力且 115 接受时按磁力提交；否则标记暂不支持 | info-hash | 同上；不把需要 Mini4K 浏览器 Cookie 的种子 URL交给 115 |
| 已核实 115 分享 | P115StrmHelper 分享转存实现；调用前做列表预检 | 分享标识摘要 + 目标目录 | 回查目标目录的文件 ID／大小、整理及媒体库 |
| M-Team 种子 | 现有 `DownloadChain.download_single` | 下载 hash | 下载器任务与 MoviePilot 历史，再等待媒体库 |

115 离线 API `add_offline_task` 接受 `links` 和可选 `path`，只回“新增数量”；提交后需按已知 info-hash 从 `offline_tasks` 对账。提交超时属于“结果不明”，先查询任务，不能马上重试。API 列表最多可能延迟约两分钟；在宽限期内查不到不代表失败。状态 2 只表示离线完成，不能直接回写片单。

115 分享现有 `add_transfer_share` 是 GET 参数且内部可能记录分享码和提取码。自动适配器应封装同一分享转存实现，改成受控 POST／进程内调用并关闭敏感日志后才启用；不把含提取码的 URL 放进查询串、插件记录或普通日志。115 Cookie、Mini4K 会话与 MoviePilot API 令牌继续保存在现有受保护配置里。

整理继续调用 P115StrmHelper 的云盘整理与 STRM 生成能力。适配层先检查插件已启用、115 客户端可用、离线和整理目录配置有效、媒体服务器扫描可用；不为这条链路引入另一个数据库或整理器。由于其自动整理待处理列表不持久化，FilmWatchlist 对账发现“离线完成但未整理”时，按已记录 info-hash 找到云端文件 ID，并调用现有整理方法一次；调用前后均检查目标目录／STRM，避免重复搬运。兼容性适配必须集中在单个 `P115TaskAdapter`，按安装版接口做版本检查，接口不符时暂停任务。

## 状态闭环与幂等

每条记录以 `media_type:media_id:season` 为媒体键，同时保存 Favsync film ID、候选 ID、来源、质量档、视频大小、info-hash／分享摘要、路由、提交时间、115 云端文件 ID 或 PT 下载 hash、最后观察和错误码。沿用 MoviePilot 插件数据存储；写入在现有运行锁内完成，按条及时持久化，不新建数据库。原有 `download_hash` 记录作为旧版 PT 任务兼容读取。

```text
DISCOVERED → EVIDENCE_READY → DECIDED → SUBMITTING → SUBMITTED
                                                   ├─ PT → LIBRARY_WAIT
                                                   └─ 115 → CLOUD_DONE → ORGANIZING → LIBRARY_WAIT
LIBRARY_WAIT → WRITEBACK_PENDING → COMPLETED
各阶段可进入 PAUSED / FAILED，只有明确失败才重新选源。
```

先保存 `SUBMITTING` 和幂等键，再调用路由；重启后优先按 info-hash／分享目标／PT hash 查询现有任务和目标文件，再决定是否补交。`SUBMITTED` 后不并行提交 PT；115 明确失败时才重新选源，并再次核实媒体库、当前任务及失败类型。`WRITEBACK_PENDING` 反复尝试 Favsync PATCH，成功才置 `COMPLETED`。媒体库核验沿用现有电影／整季规则；115 云端文件或 STRM 的存在本身不足以置 `downloaded=true`。

同一 film ID 只允许一个有效任务；同一媒体键跨片单 ID 也复用任务与入库结果。扫描开始先恢复未决状态，再搜索新条目。还要检查 MoviePilot 当前任务与下载历史，防止和已有任务重复；MoviePilot 原生订阅与本插件并发提交之间没有共用事务锁，因此本阶段仅保证插件自身幂等，并在提交前做最后一次现有任务检查。

## 实施顺序与冒烟验收

预期改动位置：`public_index.py` 扩展逐文件大小证据；`selection.py` 保留格式检查并抽出统一质量档；新增 `evidence.py`、`quality_selector.py`、`p115_task_adapter.py`、`task_router.py`；`__init__.py` 只负责扫描编排、插件配置和状态展示。新增 `public_selection_enabled`、`p115_route_enabled`、`share_115_enabled` 三个独立开关，初始均关闭；`near_size_ratio` 初始建议为 `0.10`。已有 `records` 数据按旧 PT 任务读取，不要求清空或重下。

1. **证据层**：补齐 torrent／磁力／115 分享的文件和大小预检；用一部同名电影验证年份、国家过滤；分别验证公开 BT、private BT、仅分享、未知清单。
2. **纯裁决层**：把 M-Team 搜索结果和 Mini4K 索引结果转成统一候选；以少量固定样例核对 Remux 优先、同档大小差距、相近时公网、原盘拒绝、故障暂停与 PT 兜底。预览先显示胜出理由。
3. **115 适配层**：先单条公开磁力测试提交和 info-hash 查询，再验证云端完成、重启后的补整理及 STRM／媒体库；分享转存单独开关，完成敏感日志处理后再测。只做单条真实任务，避免批量试下载。
4. **状态接线**：正式扫描统一调度并分来源入队；重复运行和重启各一次验证不重复提交；未入库保持 `downloaded=false`，完整入库后写回。保留预览默认开启和快速关闭公网路由的开关。

每一步都先在预览或单条指定 film ID 上验收，再放开全量片单。上线时不更改现有 M-Team 下载器设置或 115 既有整理目录。
