# Navidrome 收听上报历史

来源 navidrome，既有 Navidrome 0.64.2。当前实例有一个用户，源库 scrobbles 保留 2677 条记录（接入核对时），字段为 id/media_file_id/user_id/submission_time；其余媒体库字段由同一快照关联。

本实例采用既有 `collectors.snapshot()` 对 `/vol2/1000/Docker/navidrome/data/navidrome.db` 取只读一致快照，包含 WAL。不新增 API 账号或密码，不读取/写回用户密码和 JWT 字段，不修改 Navidrome 服务。API 优先的原草案在此具体调整为源库历史读取：能直接拿到已保存的上报记录，且已有只读文件权限。

- music_playback_event 的 event_type=scrobble_submission，保存原生 scrobble ID 与源库记录的 submission_time。
- external_id=scrobble:{id}，同一歌曲的重复上报及同秒上报各自保留。
- 增量按原生递增 ID，离线客户端后来提交旧时间记录也不会仅因时间早于水位而漏掉。
- 首次保存当前源库全部保留历史；明确 --since 可以缩小补采范围。源端更早清理的记录无法恢复。
- media_file 使用 LEFT JOIN；已从库中移除的歌曲仍保留上报记录，名称/作者/专辑缺失明确标记。媒体元数据是采集时库中的值，不冒充播放时历史元数据。
- submission_time 是源库保存的上报记录时间，Hub 原样采用该时间；不将它改称 Hub 接收时间，也不推断实际开始/结束或 listened_duration_seconds。歌曲 duration 只是文件时长。

默认每 300 秒检查一次。没有新记录也登记检查成功；不调用 scrobble 写入，不标 authoritative，不把历史清理当成用户删除。此方式读取源库已保存的历史，不读取 getNowPlaying，不承诺未上报的听歌活动。

nas-activity-v1 按实例/用户/业务日归组为 activity / music_day；按歌曲提供上报次数与时间，完整上报条目通过 blocks 分页。源库结构绑定当前 0.64.2，服务升级时按实际 schema 同步适配，失败不会推进水位。

依据：[当前版本 scrobble 存储实现](https://raw.githubusercontent.com/navidrome/navidrome/v0.64.2/persistence/scrobble_repository.go)、[Navidrome 上报语义](https://navidrome.org/docs/developers/subsonic-api/)。播放器需提交 scrobble，读取空结果不能证明用户没有听歌。
