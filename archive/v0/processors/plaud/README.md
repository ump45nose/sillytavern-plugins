# Plaud 转录与录音日报

正式业务入口为 `agents/nas/plaud-process.py`，Cron 包装为 `agents/nas/plaud-daily.sh`。复用原独立 Python 环境、Hermes 运行账户、Plaud 登录、Groq/CPA 凭据、本地模型及 `/vol1/1000/plaud-daily/daily-v3` 状态与缓存。私有配置位于 `/home/yuwk/.config/personal-data-hub/plaud-processing.yaml`，源码中不保存身份或密钥。

沿用 Hermes Lingjun 作业 `58d4a4c46d49`，每天 00:00–07:30 每半小时处理前一天录音。转录按连续 20 分钟分块，完整保留尾块和音频内容；Groq、Gemini、SenseVoice 使用同一块音频。07:30 后通过来源校验才提交整份融合稿，随后从融合稿生成「主要内容」「决定与待办」「待确认」摘要。说话人仍是匿名编号，跨块不自动关联本人。

Gemini 模型和接口在私有配置中声明。原生 `generateContent` 使用 `inlineData` 传输音频，格式依据 [Google 官方音频文档](https://ai.google.dev/gemini-api/docs/generate-content/audio)，通过既有 CPA 执行。修改 Gemini 路由只改变该来源的请求身份；已完成 Groq、本地稿和历史请求记录保留。每个来源块/模型/接口身份仅请求一次；每日期最多一次自动融合；摘要同一输入仅请求一次。失败或中断保留哨兵，不自动删除后重试。

2026-10-09 对照实测：当前 CPA 的 3.8/3.7 Flash 上游对完整真实录音返回 `promptFeedback.blockReason=OTHER`；Pro 路由能够返回转录。按用户要求重新开放隐藏的 Gemini 音频模型，原 `gemini-3-flash` 及其他候选通过完整音频测试，正式配置恢复原 3 Flash。完整诊断保存在来源块的 `gemini-response-diagnostic.json`；原文另存 `gemini-raw-transcript.md`。仅为模型遗漏的时间戳添加方括号，不改时间、文字或说话人；截断、越界及倒序时间拒绝成为有效来源。原生请求实现摘要也纳入运行和请求身份，修复后保留旧失败证据并沿用 Groq/SenseVoice 缓存。逐个模型测试和实际补跑结果见 `docs/plaud-gemini-diagnostics.md`。

产物：`sources/` 保存分源块，`runs/DATE/HASH/` 保存完整输入、校验和融合/摘要请求状态；`output/DATE.md` 是完整录音日报，`output/DATE.summary.md` 是其摘要；`status/DATE.json` 保存每日期状态，`latest.json` 为最近状态。旧实验仍在 `legacy/plaud`，正式任务从本目录运行。

personal-hub 的 Plaud 采集器将产物同原音频一起归档：`recording` 详情包含 `transcript`、`transcripts`、`summary`、`processing`；`recording_transcript` 是具名来源草稿，完整且哈希匹配的分块标 `source_ready`，缺块或历史筛选稿标 `source_partial`；`recording_daily_report` 是录音日报；`recording_summary` 是每日摘要。来源草稿标 `transcript_is_draft=true`，不冒充三源完成稿。摘要的 `summary_scope=day` 明确它覆盖该日期全部录音。

Gemini 缺失或质量校验失败时，完整 Groq 来源仍可生成独立日报及摘要草稿（`output/DATE.draft.md`、`output/DATE.draft-summary.md`），接口标 `draft=true` / `summary_status=draft`，同时保留实际处理失败状态。本地 SenseVoice 独立运行。草稿不参与替代缺失来源的三源多数判断；三源融合通过后优先展示正式结果。

HTTP：`GET /api/v1/recordings/{hub_record_id}/content`；MCP：`get_recording_content(record_id)`。通用列表支持上述 `kind`，详情继续支持 `get_data_record`。列表保持有界预览，完整文字从详情读取。原 Bearer/OAuth 和查看端只读凭据继续有效。

验证：`PYTHONPATH=processors/plaud/src collectors/plaud/.venv/bin/python processors/plaud/smoke_daily_v3.py` 检查完整覆盖、25 秒尾块、缓存及融合/摘要请求门禁；`.venv/bin/python checks/plaud-content-smoke.py` 检查正文关联、缺块/错哈希、重复归档和鉴权接口。两者使用临时数据和模拟云端，不调用真实 ASR。

`PYTHONPATH=processors/plaud/src collectors/plaud/.venv/bin/python processors/plaud/smoke_gemini_native.py` 验证 Gemini 原文保留、时间格式修复和无效响应隔离，不请求云端。
