# PLAUD 每日录音同步

此目录是原 Plaud 项目的源码保留区，由 Personal Data Hub 统一管理。聚合系统的下载与归档入口位于 `collectors/plaud` 和 `agents/nas/plaud-sync.py`。本次迁移不注册或恢复 ASR、融合及其他旧任务；下文保留原项目的历史说明，其中旧项目路径已移除。设备配置和 Python 环境在仓库外，当前入口直接使用本仓库。新检出可参考 `config.example.yaml`、`daily-v3.example.yaml`，通过 `RR_CONFIG` 或 `--config` 指定私有配置。

## 当前自动运行入口：三源 v3

Hermes Lingjun 的 `plaud-daily-three-source-v3`（ID `58d4a4c46d49`）由
`/home/yuwk/cron/model/plaud-daily.sh` 调用 `plaud_daily.daily_v3`，使用
no-agent 模式；Hermes 不运行额外的 LLM agent，业务代码自行调用 ASR 和融合 API。

- Asia/Taipei，每天 00:00–07:30 每半小时触发，默认处理前一天。
- 处理该日期全部云端录音，不使用 CAM++、本人 ±15 分钟窗口或 VAD 删除内容。
  日期按录音开始时间归属；跨午夜录音保持完整，不宣称按自然日拆分已验收。
- 每条音频按连续 20 分钟分块，尾块按实际时长处理；Groq Whisper large-v3、
  Gemini、SenseVoice 都使用同一块音频哈希，语言固定 `zh`。
- 转写按源音频、模型、提示词和参数缓存；后到的录音不会重跑已完成的块。
- 汇总为**全天一份 Markdown**。来源缺失、Gemini 时间戳越界/倒退、音频或哈希
  不一致、输入超限时停止，不拿失效来源参与投票。
- 07:30 起，通过校验后自动把完整 Markdown 一次提交 CPA `grok-4.7`。
  每日期最多一次自动请求；不拆分融合、不自动重试。超时或进程中断也保留请求哨兵。
- 无多数关键事实保留 `[候选｜候选]` 和 `🔴`，普通措辞可润色；不挖空数字。
  新录音、不同分块的 Speaker 编号不关联为同一人，更不自动认成“我”。
- 成功或正常等待时 stdout 为空；故障返回非零退出码，证据留在 Hermes Cron
  执行记录与 `daily-v3/latest.json`。不新增 Telegram/Bark 推送或系统 crontab。

配置：[daily-v3.yaml](daily-v3.yaml)。新状态和产物位于
`/vol1/1000/plaud-daily/daily-v3/`，与旧 `state/`、`work/`、声纹模板和历史稿隔离。
最终稿为 `daily-v3/output/YYYY-MM-DD.md`；完整输入、原始三稿、用量和失败状态
位于 `daily-v3/runs/DATE/HASH/`，ASR 块缓存位于 `daily-v3/sources/`。
本版不自动删除原音频；14 天保留策略尚未启用，避免删除待核听材料。

```bash
cd /vol1/1000/Code/plaud-daily
sudo -u hermes .venv/bin/python -m plaud_daily.daily_v3 doctor
# 交互式 MCP 登录；远程电脑须先将本机 8199 转发到 NAS 的 8199。
sudo -u hermes .venv/bin/python -m plaud_daily.daily_v3 login
sudo -u hermes .venv/bin/python -m plaud_daily.daily_v3 run-date --date 2026-10-05
```

凭据：Plaud MCP 登录使用 Hermes 系统账号的
`/home/hermes/.plaud/tokens-mcp.json`（600）；Groq key 使用
`/home/hermes/.hermes/secrets/plaud-daily/groq.key`（属主 hermes，600）；CPA
复用 Hermes 根 `.env`。不从聊天历史取密钥，不共用桌面插件或 Plaud CLI 的登录态。
如果 Groq 免费账号出现额度/限流错误，本轮停止并留下错误；全天调用量不保证免费额度
足够。切勿将凭据写入项目配置、Cron 清单或日志。

基本冒烟：`.venv/bin/python smoke_daily_v3.py` 使用本地合成音频和模拟云端结果，
检查 1,225 秒全覆盖、25 秒尾块、缓存重跑和单次完整 Markdown 请求哨兵，
不调用外部服务。真实云端及全天质量仍须实跑验证，来源校验不是准确率验收。

旧 M1 与下方历史实验保留作回退/追溯，**不是当前 Cron 入口**。

## 旧 M1 链路（保留）

声纹分离与按话轮转写的离线金标试验见 [GOLD_DIARIZATION_2026-09-28.md](GOLD_DIARIZATION_2026-09-28.md)。试验未验收，生产链路与 Cron 未切换。

旧 M1 实现 `plaud_mcp` 与 `local_dir` 同步，以及 `sync → preprocess → asr → render`。以下说明只适用于旧入口。默认在本机以 SQLite 和文件保存业务状态，不需要新容器或数据库。

## 运行

```bash
cd /home/yuwk/code/plaud-daily
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/recording-review sync --date 2026-09-25
.venv/bin/recording-review preprocess --recording-id <id>
.venv/bin/recording-review asr --recording-id <id>
.venv/bin/recording-review render --date 2026-09-25
```

只测试一条录音时，使用 `.venv/bin/recording-review render-recording --recording-id ID`，产物位于 `work/ID/transcript.md`，并明确标注不是完整每日稿。

`run-date --date YYYY-MM-DD` 在单实例文件锁下串行执行以上链路。默认日期是 Asia/Taipei 的前一天。`inspect` 查看 SQLite 业务状态；`retry --recording-id ID --from-stage preprocess` 显式重跑。每条命令 stdout 只有一行 JSON，MCP 自身的诊断日志可能写 stderr。

ASR 默认只处理每段【我】语音起止时间前后各 15 分钟内的 VAD 片段；同一日期中已发现并预处理的相邻录音可互相提供窗口。人工确认“含本人”的混合片段也提供检索锚点，但整段标【未确定】，不把他人台词误署为【我】。完整 `segments.jsonl` 和 `selection.jsonl` 保留筛选证据，窗口外不送 ASR。整日没有可信【我】锚点时，ASR 标为 `waiting/no_me_anchor`、不发布空稿；已有原音频和历史全量测试稿不自动删除。SenseVoice 固定以单值 `zh` 识别；正式 Markdown 只发布标为 `zh` 且不含日文假名或韩文字形的片段。被过滤的原识别结果及原因留在 `asr.jsonl` 审计，不进入稿件。纯汉字的日语仍可能无法凭文字形态区分，语言检测和声纹都需要人工标注验收。

当前 `me_threshold=0.65` 是未验收的试调值。2026-09-24 两个含本人声音的 MP3 窗口虽出现【我】预测，但用户反馈自己的台词被标为【未确定】，不能把“窗口有【我】”当作识别正确；另有裸 Opus 候选待核听。声纹漏识别与模型对照见 `VOICEPRINT_DIAG_2026-09-26.md`；尚无独立 precision/recall/F1。

【未确定】不能仅靠降低 `me_threshold` 消除：两条 5 小时录音中分别有 217/248、380/391 个【未确定】片段未计算声纹分数，多数是因为短于当前 1.5 秒门槛。用户核听认为其中大部分是本人，后续应以分段标注验证短片段的拼接/上下文继承方案；不能把所有【未确定】无条件改标【我】。

模型路径和下载版本见 `config.yaml`。SenseVoice int8、Silero VAD、CAM++ 都在本地推理，外部转写 API 默认不存在。未经纯本人语音 `enroll --input PATH` 注册，所有说话人片段都会标为 `uncertain`，Markdown 显示【未确定】，不会自动推断为【我】。

`local_dir` 适配器使用每条录音一份 JSON sidecar，含 `recording_id`、UTC `start_at`、`duration_ms`、相对 `path`。设置 `RR_SYNC_PROVIDER=local_dir` 并在配置中指定目录后可独立验证，无须 Plaud 凭据。

原始音频默认保留 14 天是后续运维策略；M1 不自动删除任何文件。M0 的七日刷新、跨午夜和全天时效证据仍须补齐；M2 声纹指标和 M3 Cron 验收也未完成。

## 9/26 三源融合离线实验

当前试用选择（2026-09-28）：后续三源融合实验先沿用 v3 的并列候选格式，例如 `[前端｜后端]`；对无多数的关键事实保留 `🔴`，不强迫 Grok 猜出单一答案。v4 确定性稿只保留作对照，不作为当前选用稿。待积累数天不同场景的录音与人工核听结果后再评估是否改动；此选择尚未切换生产转写链路或 Cron。

当前 v3 使用独立的审阅门禁：运行 `.venv/bin/python -m plaud_daily.fusion_v3 prepare-input`，仅从既有 Gemini、Groq、SenseVoice 稿生成 `fusion-v3-review-gated/fusion-input-v3.md`，不重跑 ASR，不读取 Plaud 转写，也不调用 CPA。必须把整份文件和当前 SHA-256 交用户审阅；用户修改后重新计算并再次审阅。只有用户明确确认该 SHA-256 后，才能运行 `.venv/bin/python -m plaud_daily.fusion_v3 submit-approved --approved-sha256 HASH`。后者仅向 CPA `grok-4.7` 发送一次完整 Markdown；不拆块、不自动重试。失败时不发布最终稿。实验文件不写入生产链路。

确定性改写另用 `.venv/bin/python -m plaud_daily.fusion_decisive`：将新输出要求置于同一份已审阅 Markdown 的开头，作为单条用户消息一次提交，要求 Grok 选定一个说法，不再列候选或 `🔴`。产物另存 `fusion-v4-decisive/`，不覆盖 v3，也不自动重试。

以下 `fusion_trial` 为旧版逐块实验，保留供历史追溯；不要用于 v3：

`python -m plaud_daily.fusion_trial` 只处理已锁定音频哈希的 13:47–14:07 片段。它复用 Groq、Gemini、SenseVoice 的完整既有转写；不重新转录，也不读取或写入生产 SQLite、正式转写稿、模板及 Cron。实验不施加上述 ±15 分钟筛选，保留整段内容；当前样本无超过 30 秒的明确静音区间。

先运行 `.venv/bin/python -m plaud_daily.fusion_trial --prepare-only` 检查输入、粗时间对齐和 CAM++ 疑点。正式融合需从已有 CPA 凭据注入 `CPA_PUBLIC_API_KEY`，再运行同一模块（不加 `--prepare-only`）；使用 CPA `grok-4.7`，每个请求都附带三份全文。遇到 CPA 失败会保留已完成的逐块检查点，不发布半成品稿。已完成后可用 `--render-only` 在不调用 CPA 的情况下从检查点生成清理版 Markdown。

版本化产物位于 `/vol1/1000/plaud-daily/experiments/2026-09-26-chat-134700-140700/fusion-grok-4.7-<输入哈希>/`。`aligned.jsonl`、`speaker-evidence-v2.jsonl`、`grok-chunk-*.json` 保留来源和决策证据；`transcript-clean-v2.md` 与 `review-clean-v2.md` 分别是可读实验稿和核听清单。Gemini 匿名 Speaker 1/2 只在这段暂映射为我/他人；CAM++ 的 `≥0.90/≤0.50` 仅对至少 3 秒清晰单人疑点允许改标，不代表已验收准确率。
