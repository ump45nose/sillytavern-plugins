# M3：当前来源的阅读控件

服务端负责加工，Mac 负责控件。本阶段不修改客户端源码；功能验收留到采集侧完成后统一做一轮。此前 M1/M2 的分页、revision、证据和附件接口继续使用。

## 读取入口

`GET /api/v1/contents` 新增 `type` 筛选。支持 `document`、`conversation`、`activity`、`recording`、`metric_day`、`business_object`、`status`，其余筛选和分页参数不变。切换任何筛选时清空 cursor。

默认列表排除模型分析、Hermes 执行日志、原始电脑观察和辅助状态。指定 source 或 variant 可以查看辅助内容；`type=status` 可以打开状态列表。处理状态从 `processing.state` 读取，来源自身状态在 metadata 中，两者不能混用。

列表不含大正文和类型元数据。打开详情后读 metadata；正文继续逐页读取 `/blocks?revision=...&after=...`，409 后刷新详情，404 后撤下对象。引用从 blocks.refs 和 `/evidence` 取得，附件按现有 `/api/v1/assets/{asset_id}` 入口打开，不用本地路径猜附件。

## 类型路由

| type / variant | 需要的控件 | 详情字段和规则 |
| --- | --- | --- |
| conversation / email | 邮件头、正文、折叠引用、附件 | subject、sender、recipients、message_id、in_reply_to、references、account；可靠线程采集未完成，当前是一封邮件一个对象。正文是 text，quoted=true 可折叠但不能丢弃 |
| activity / activity_summary | 活动摘要、背景折叠区、来源引用 | title、description、applications、interval。块 role=background 默认折叠；activity 是上游摘要。不得把 10min/6h 标签算成活跃时长 |
| activity / activity_observations | 按时间查看电脑观察及原始文本 | started_at、ended_at 是观察范围；event_count 不是操作次数或活跃时间。event 块包含 application/window/url，后续 text 块显示 AX 或选中文本 |
| recording / recording | 音频播放器、转录、分源稿入口、日报入口 | duration_ms、download_state、transcription_status、transcript_is_draft、audio_assets、transcript_sources、daily_report、daily_summary；日报摘要只能标为“当天摘要” |
| document / recording_transcript | 草稿标记、转录、有效时间跳转 | engine、status、draft、scope、recording、audio_assets。transcript_segment 块的 time_valid=true 且 seek_seconds 非空时才允许跳转；speaker 不跨来源/音频块合并 |
| document / recording_daily_report、recording_summary | 按日文档、草稿提示 | scope=day。不能拿它替换单份录音的完整正文 |
| metric_day / health_day、finance_day、usage_day、network_day | 日指标、单位、完整组成下钻 | business_date、timezone、metrics。null 显示缺失；账单金额和汇总是十进制字符串，币种分组；费用 cost_basis=estimated；不同来源/测量点的网络数据不可直接相加 |
| business_object / calendar_event | 日历详情 | metadata.fields 的 start/end/status/calendar/all_day；全天事件的结束日期不包含当天 |
| business_object / google_task | 任务详情 | list_id/list_title/status/due/completed/parent/webViewLink；due 是日期，不构造小时截止时间；只代表当前快照 |
| business_object / git_commit | 提交详情、仓库和提交链接 | repo/sha/url/author/committer；message 正文完整保留。不能显示成 PR 或完整代码活动统计 |
| business_object / people、facts、reminders、interactions | 联系人、事实、提醒和交流详情 | metadata.fields，已有 person_id；事实有 confidence/status，提醒有 due_at/status。微信仍走 M2 会话 |
| document / memory、legacy_review | 记忆文档、历史产物标签 | memory_metadata/categories/synthesized/replaced_by/expiration_date；这里只读既有 Mem0，不新增记忆归纳或基线 |
| status / execution_status、collector_status、configuration、archived_artifact、source_evidence | 辅助信息页、来源原件入口 | metadata.fields。实验文件、诊断和配置不混入普通内容；coverage.business_content=false 不能解释为已经生成业务正文 |

## 展示细节

邮件 HTML 已由服务端转成文本，客户端不要再次解释为 HTML。HTML 阅读块的 offset_basis=converted_text，字符区间不能直接用于截取归档 HTML；原始 HTML 仍在来源记录里。纯文本邮件字符区间对应原文。仅明确的 `>` 引用行有 quoted 标记，其他引用格式保留原样。

电脑摘要的前置信息已经从正文移出。后台保留既有背景、Recording summary 与 Citations 的分区，原文顺序不变。`source_citations` 中带 content_id 的引用可打开对应观察；availability=resolve_on_open 表示目标可能尚未采集，不代表已完成证据核验。外部路径仅作来源标识，不执行、不当成本机路径。当前归档没有可靠的活动覆盖区间，coverage_interval=null，界面不叠加摘要时长、不推导专注时长。后续若要合并 6h/10min，需先取得可核验的覆盖关系。

转录的 transcript_verbatim 块是完整归档正文，默认折叠；有 transcript_segment 时主阅读区用片段块，无片段时使用 transcript。片段文本和全稿均来自同一归档，勿重复显示。音频不在该对象附件列表时使用 metadata.audio_assets。未取到录音或时间戳无效时只显示文本。

指标组成放在块分页中，头部不塞入全部样本。健康 measurement 块包含 metric/time/value/source_unit/origin/device；日指标单位可能不同于样本单位（睡眠日值为小时，样本为秒）。finance_day 的块是一笔账单；usage_day 的块分别是设备、模型或工具，模型与工具是拆分视图，不能再加到设备总量；network_day 的块是现有小时粒度，更新替换累计值。

fields 块的 metadata 是结构化字段，用字段控件渲染；text 是搜索投影，不要求界面展示 Python 字典形式。正文类型仍只需 markdown/text，新增 fields/measurement 走专用控件。

示例见 [m3-api-fixtures.json](m3-api-fixtures.json)。全部为虚构材料，不含真实账号、消息、录音或凭据。
