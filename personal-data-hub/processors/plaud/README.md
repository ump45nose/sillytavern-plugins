# Plaud 转录与录音日报

正式业务入口为 `agents/nas/plaud-process.py`，Cron 包装为 `agents/nas/plaud-daily.sh`。复用原独立 Python 环境、Hermes 运行账户、Plaud 登录、Groq/CPA 凭据、本地模型及 `/vol1/1000/plaud-daily/daily-v3` 状态与缓存。私有配置位于 `/home/yuwk/.config/personal-data-hub/plaud-processing.yaml`，源码中不保存身份或密钥。

沿用 Hermes Lingjun 作业 `58d4a4c46d49`，全天每半小时执行 `run-pending --cron`。回查前 7 个完整日期的录音（上游查询留出一天时区余量），检查输入清单并轮流处理未完成日期；迟到录音会重新打开已完成日期，旧运行和正式稿保留。已收到的未完成录音不会因超过回查窗口而丢出队列。优先复用可读、哈希匹配的下载归档；运行账户无法读取保护归档时，继续用既有 Plaud 授权同步，不扩大目录权限。

转录按连续 20 分钟分块，完整保留尾块和音频内容。Groq、Gemini、SenseVoice 覆盖同一完整音频块；Gemini 原生请求进一步按连续 5 分钟切分，时间越界或倒序时自动按 150 / 75 秒继续拆分，成功小段缓存保留。来源校验通过后提交整份融合稿，随后生成「主要内容」「决定与待办」「待确认」摘要。说话人仍是匿名编号，跨块不自动关联本人。

Gemini 模型和接口在私有配置中声明。原生 `generateContent` 使用 `inlineData` 传输音频，格式依据 [Google 官方音频文档](https://ai.google.dev/gemini-api/docs/generate-content/audio)，通过既有 CPA 执行。修改 Gemini 路由只改变该来源的请求身份；已完成 Groq、本地稿和历史请求记录保留。成功请求及其产物按输入身份复用；失败记录写入历史，按 30 秒至 6 小时退避自动重试，中断请求在 20 分钟后可恢复。云端来源子进程有 720 秒时限，融合和摘要请求为 600 秒；Cron 总时限沿用 Lingjun 的 8100 秒，重叠运行由持久锁跳过。稿件或输入改变时采用新的请求身份，避免旧哨兵永久阻止恢复。

Gemini 的原始响应、完整诊断及重试历史分别保存。解析支持原时间戳、毫秒 SRT 区间、未标注说话人的片段（标 `?`），不擅自把有歧义的时分秒改作分秒。已保存的有效 SRT 会先重新解析，避免重复云端请求；越界和倒序仍被拒绝，不排序、裁剪或缩放时间。实际根因和生产验收见 [部署维护记录](../../docs/deployment.md)。

新的原生请求用 [Gemini 结构化输出](https://ai.google.dev/api/generate-content) 返回明确的 `MM:SS.mmm` 格式 `start_timestamp`、匿名说话人和原文。真实验收发现数值请求会把 `01:08.312` 写成 `108.312`，因此不要求模型换算秒数，也不擅自修正旧错误数值。仍检查时间格式、范围和顺序，原始 JSON 另存；已验证的数值、Markdown / SRT 缓存继续可用。

融合响应省略说话人标签时明确标为未知 `Speaker ?`，不推断身份；已有说话人标签保留。发布前继续验证录音覆盖和时间范围、顺序；同一输入的已保存响应先复验，合法响应直接发布，不再次请求融合。原始响应和失败记录保留。产物使用独立暂存文件，中断残留的 `.part` 不会阻止下次继续。

2026-10-09 对照实测：当前 CPA 的 3.8/3.7 Flash 上游对完整真实录音返回 `promptFeedback.blockReason=OTHER`；Pro 路由能够返回转录。按用户要求重新开放隐藏的 Gemini 音频模型，原 `gemini-3-flash` 及其他候选通过完整音频测试，正式配置恢复原 3 Flash。完整诊断保存在来源块的 `gemini-response-diagnostic.json`；原文另存 `gemini-raw-transcript.md`。仅为模型遗漏的时间戳添加方括号，不改时间、文字或说话人；截断、越界及倒序时间拒绝成为有效来源。原生请求实现摘要也纳入运行和请求身份，修复后保留旧失败证据并沿用 Groq/SenseVoice 缓存。逐个模型测试和实际补跑结果见 `docs/plaud-gemini-diagnostics.md`。

产物：`sources/` 保存分源块，`runs/DATE/HASH/` 保存完整输入、校验和融合/摘要请求状态；`output/DATE.md` 是完整录音日报，`output/DATE.summary.md` 是其摘要；`status/DATE.json` 保存每日期状态，`latest.json` 为最近状态。旧实验仍在 `legacy/plaud`，正式任务从本目录运行。

personal-hub 的 Plaud 采集器将产物同原音频一起归档：`recording` 详情包含 `transcript`、`transcripts`、`summary`、`processing`；`recording_transcript` 是具名来源草稿，完整且哈希匹配的分块标 `source_ready`，缺块或历史筛选稿标 `source_partial`；`recording_daily_report` 是录音日报；`recording_summary` 是每日摘要。来源草稿标 `transcript_is_draft=true`，不冒充三源完成稿。摘要的 `summary_scope=day` 明确它覆盖该日期全部录音。

Gemini 缺失或质量校验失败时，完整 Groq 来源仍可生成独立日报及摘要草稿（`output/DATE.draft.md`、`output/DATE.draft-summary.md`），接口标 `draft=true` / `summary_status=draft`，同时保留实际处理失败状态。本地 SenseVoice 独立运行。草稿不参与替代缺失来源的三源多数判断；三源融合通过后优先展示正式结果。

HTTP：`GET /api/v1/recordings/{hub_record_id}/content`；MCP：`get_recording_content(record_id)`。通用列表支持上述 `kind`，详情继续支持 `get_data_record`。列表保持有界预览，完整文字从详情读取。原 Bearer/OAuth 和查看端只读凭据继续有效。

验证：`PYTHONPATH=processors/plaud/src collectors/plaud/.venv/bin/python processors/plaud/smoke_daily_v3.py` 检查完整覆盖、25 秒尾块、缓存及融合/摘要请求门禁；`.venv/bin/python checks/plaud-content-smoke.py` 检查正文关联、缺块/错哈希、重复归档和鉴权接口。两者使用临时数据和模拟云端，不调用真实 ASR。

`PYTHONPATH=processors/plaud/src collectors/plaud/.venv/bin/python processors/plaud/smoke_gemini_native.py` 验证 Gemini 原文保留、时间格式修复和无效响应隔离，不请求云端。

`PYTHONPATH=processors/plaud/src collectors/plaud/.venv/bin/python processors/plaud/smoke_unattended.py` 验证退避、中断恢复、缺失产物恢复、迟到录音、保护归档回退和未完成日期保留。所有 smoke 必须设置上述 `PYTHONPATH`；独立环境的旧 editable 安装仍指向 legacy，正式入口会显式选择本目录。
