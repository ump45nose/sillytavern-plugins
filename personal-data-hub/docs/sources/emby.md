# Emby 当前播放观察

来源 emby，既有 embyserver 4.10.1.0。宿主从既有 `http://127.0.0.1:28096/emby/Sessions` 读取，复用 emby-theme-worker 的 API 密钥文件；不改 Emby 镜像、用户、网络、密钥或媒体卷。

个人账户按与现有 Navidrome 账户同名的 Emby 用户 ID 固定过滤；其他两个账户不采集。不以“允许远程控制该会话”代替用户过滤，也不把 AdditionalUsers 当作确定的本人观看。

- media_playback_snapshot 保存会话、条目、设备、客户端、暂停、进度、倍速与实际观察时间。
- external_id 由实例、用户、会话、条目、采样槽组成；默认每 60 秒采一次。重新采同一槽可以形成同一观察记录的新版本，重复播放不会按影片 ID 全局去重。
- 原件保存明确的播放字段投影，排除媒体 URL、OpenToken、认证头与密钥。PositionTicks/RunTimeTicks 仅转换单位，不推算观看时长。
- Record.occurred_at 保持空，normalized.observed_at 是观察时间。processed 日对象的时间范围也只代表观察范围。
- 空会话仍登记本轮检查成功，不制造“停止播放”事件，不标 authoritative，不补造接入前的历史。

nas-activity-v1 按实例/用户/业务日归组为 activity / media_day；详情按条目和会话提供观察组，正文是完整观察点，均有 record/hash 引用。短于采样间隔的播放、服务离线、未上报客户端都可能缺失。media_duration_seconds 是影片总长度，不是本人观看时间。

配置只在已有私有 Hub 配置增加来源。Mac 按 [M4 控件需求](../client-requirements/m4-nas-git.md)接入；未运行功能测试。

依据：[Emby getSessions](https://dev.emby.media/reference/RestAPI/SessionsService/getSessions.html)。当前会话接口提供状态，不能当作完整播放历史。
