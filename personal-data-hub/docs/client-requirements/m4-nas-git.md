# M4：NAS 活动与 Git PR

本节点只修改服务端，Mac 接入复用 M1–M3 已有列表、类型详情、块分页和证据控件。功能检查统一留到采集侧完成之后。

## NAS 日活动

通过 `/api/v1/contents?source=emby&variant=media_day`、`?source=navidrome&variant=music_day` 读取日对象；type 都是 activity，schema_version=1。空活动日不生成对象，应从 sources 页查看最近检查状态，不能显示为采集失败。

详情 metadata 包含 service、business_date、timezone、source_user_id、capture、time_basis、record_count、item_count 和 items。不要把 record_count 显示成确定的“播放次数”：Emby 是观察点数量，Navidrome 是上报记录数量。

items 每项提供 item_id、title、artist/album 或 player/device/session_id、count、count_label、first_time、last_time、media_duration_seconds 与 link。先展示条目列表，再按 group_index 从块分页展开完整时间列表。始终翻到 next_after=null，不能拿头部 items 代替正文和全部引用。

| 来源 | 展示文案与规则 |
| --- | --- |
| Emby / media_day | “播放观察”，显示观察时间、客户端、设备、暂停和进度。first_time/last_time 是观察范围，不能当作连续观看时段；media_duration_seconds 是媒体总长，watched_duration_seconds 为空 |
| Navidrome / music_day | “收听上报”，显示歌曲、作者、专辑、上报次数和各时间。time_basis=source_submission_time，不当作完整听歌开始时间；listened_duration_seconds 为空 |

正文块 type=fields，metadata.role 为 observation 或 scrobble_submission；group_index 对应 items 索引。metadata.time 是实际观察/上报时间，position_seconds 为实际源端进度，paused=null 表示未知。值为零要照常显示，值为 null 不能替换成零。

warnings 的 sampling_may_miss_short_playback、client_submission_is_not_measured_listening_duration、item_metadata_missing 分别显示采样限制、上报语义和媒体元数据缺失提示。缺失条目仍能展开时间和依据。

link 只跳转源服务；Navidrome 当前提供音乐服务入口，item_id 用于搜索定位，没有假造精确条目链接。日对象不需要音视频播放器，也不要用源地址拉取未经归档的媒体原件。

## 本人创建的 PR

`/api/v1/contents?source=git&variant=git_pull_request` 返回 business_object / git_pull_request。标题是 PR 标题，完整描述从 markdown 块读取，metadata.fields 提供 repo、number、state、draft、merged、created_at、updated_at、closed_at、merged_at、url、author、base_branch、head_branch。

merged=true 或源端 merged_at 非空显示“已合并”；closed 且没有合并依据显示“已关闭”；其他按 draft/open 显示。未知 merged 不能显示成确定未合并。created_at 是创建时间，updated_at 是源端更新时间，不用 Hub 首次看到的时间生成状态转换。

history=observed_object_versions，collection_scope=authored_pull_requests。这里只覆盖本人创建的 PR；不要显示成全部评审或协作活动。Git 提交仍使用 M3 已有控件，提交和 PR 分别归档，不从提交猜 PR 合并关系。

引用、revision、409/404 和搜索规则均保持既有契约。示例见 [m4-api-fixtures.json](m4-api-fixtures.json)，全部为虚构材料。
