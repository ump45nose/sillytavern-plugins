# PLAUD 声纹改造：金标与离线试验（未切换生产）

## 当前边界

- 生产仍是 VAD 逐段 CAM++／SenseVoice `zh`；唯一活跃本人模板仍为 `voiceprints/me/self-2026-09-26-five-clips.json`。本试验不写生产 `segments.jsonl`、`asr.jsonl`、每日 Markdown、SQLite 或 Hermes Cron。
- 三段 10 分钟金标音频已导出到 `/vol1/1000/plaud-daily/gold/v1/`，每段有 16 kHz 单声道无损 WAV、核听 MP3、来源哈希、旧稿候选 TSV。旧标签和旧文字均不是人工真值。
- 9/26 13:52:02–13:52:06 注册样本在闲聊段中被排除，不参与评估。9/24 旧本人片段只作验证，不加入模板。
- 只有用户逐句核听三个完整音频、纠正身份和文字，填完 `annotations.tsv` 并明确确认无漏听语音后，才能运行 `plaud_daily.gold finalize --scene ... --confirmed-by-user`。不要由模型填金标。

## 人工标注约定

运行 `/home/yuwk/code/plaud-daily/.venv/bin/python -m plaud_daily.gold validate` 查看缺项。TSV 中 `start_ms/end_ms` 是相对 10 分钟切片起点；可增删、拆分行。`gold_speaker` 填 `me`、`other`、`overlap`、`background` 或 `unintelligible`，`gold_text` 写听到的原话。两人同时说话可写同一时间范围的两行，分别标 `me`、`other`；此类时段从主声纹指标排除、单列重叠检出。听不清不要猜字。注册样本行预置 `exclude=1`，不得改成评估真值。

金标音频是经用户同意的长期本地评测例外；原始全天录音仍按原有 14 天策略。金标目录已设为 0700，音频文件为 0640。评估工具校验音频和标注哈希；修改标注后需重新由用户确认定稿。

## 已完成的基本冒烟

| 10 分钟场景 | 旧稿候选行 | 分离时间段 | 匿名簇 | 重叠时间段 | 候选【我】 | 分离耗时 / 峰值 RSS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 9/24 会议 10:32 | 67 | 118 | 29 | 70 | 11 | 56.25 秒 / 471 MiB |
| 9/26 闲聊 13:47 | 52 | 141 | 50 | 25 | 32 | 44.17 秒 / 513 MiB |
| 9/26 车内 12:05 | 52 | 123 | 40 | 24 | 0 | 41.99 秒 / 454 MiB |

聚类阈值 0.5、本人候选阈值 0.65 **均未校准**。大量匿名簇、车内 0 条候选【我】说明当前结果绝不能上线或作为准确率结论。试验使用已安装的 pyannote segmentation-3.0 int8 + CAM++；每簇只取非重叠且至少 1.5 秒的片段形成稳健质心，短句随簇但簇证据不足时仍【未确定】。输出 `turns.jsonl`、`clusters.jsonl`、`asr_units.jsonl`、`summary.json` 位于各金标目录的 `trial/diarization-cam-*/` 下。

会议场景的 112 个新话轮已用本地 SenseVoice `zh` 转写，仅为未验收试验稿；无人工金标，无法计算 CER。`plaud_daily.asr_gold_trial` 可在金标定稿后，对同一组人工话轮分别运行旧 VAD 碎片输入与合并话轮输入，并按【我】、【他人】分别报告 CER。`plaud_daily.evaluate_trial` 在人工定稿后计算时长加权的身份 precision/recall/F1；两者均拒绝未定稿金标。

## 后续阶段门

1. 人工完成三段逐句真值，包含旧 VAD 未捕获的语音；至少标出明确的本人和他人负例。金标定稿前不调身份阈值，也不从模型标签造“真值”。
2. 用金标比较 CAM++ 与（若 CAM++ 未达标）ERes2NetV2、聚类阈值和身份阈值；需有跨场景留出或新录音盲测，不能用注册片段验收。目标：本人时长加权 F1 ≥0.90、precision/recall 各 ≥0.85；逐场景报告和重叠单列。
3. 金标上 A/B SenseVoice 碎片与整段，并检查术语纠错；Paraformer＋热词仍需单独锁定本地模型和可复现 CPU 运行时。当前环境没有 `funasr`/`torch` 和 Paraformer 模型，不允许静默下载或虚报比较结果。
4. 【背景】分类须独立验证不会隐藏本人台词；目前未引入音量裁决、未过滤背景内容。ASR 与声纹都达门槛后，才以版本化产物切换生产并跑 5 小时录音、检查 ≤2 GiB 峰值、边界、幂等和最终 Markdown。Cron／同步不变。

## 复现命令

```bash
/home/yuwk/code/plaud-daily/.venv/bin/python -m plaud_daily.gold validate
/home/yuwk/code/plaud-daily/.venv/bin/python -m plaud_daily.diarization_trial --scene meeting-2026-09-24
/home/yuwk/code/plaud-daily/.venv/bin/python -m plaud_daily.asr_trial --experiment /vol1/1000/plaud-daily/gold/v1/meeting-2026-09-24/trial/diarization-cam-6386557a7cb2
```

定稿后才运行 `gold finalize`、`evaluate_trial` 与 `asr_gold_trial`。每个试验以源音频、模型、模板、参数哈希命名或校验；不会覆盖既有正式稿。
