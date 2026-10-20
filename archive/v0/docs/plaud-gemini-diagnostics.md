# Plaud Gemini 音频请求排障

日期：2026-10-09；访问侧：NAS Hermes 作业账户 → 局域网既有 CPA 8317 → Antigravity 上游。CPA 为 v8.0.21 / 54946fa；正式服务仍在 ai 组，无容器、网络、认证或持久卷变更。

初始模型清单只发布 `gemini-3.8-flash-high` 和 `gemini-pro-agent`，均来自 Antigravity。CPA 日志分别显示实际上游模型为 `gemini-3.8-flash-n`、`gemini-pro-default`。配置中没有其他 Gemini API Key 渠道。原任务使用的 `gemini-3-flash` 实际被 CPA 的 oauth-excluded-models 隐藏，这是旧任务 unknown provider 失败的配置原因。

对照使用 10 月 8 日长录音的第一块，连续 1,200 秒，不提供既有转写稿。原音频及完整响应保存在业务数据目录 `daily-v3/diagnostics/20261009-gemini/`，不进入 Git。

| 对照 | Flash 结果 |
| --- | --- |
| 纯文本，仅要求回复 OK | STOP，返回 OK |
| 3 秒中性音调 MP3 | STOP，有音频描述 |
| 原提示、同一真实语音前 30 秒 MP3 | OTHER，无候选 |
| 原提示、同一真实语音前 30 秒 WAV | STOP，带时间戳转录 |
| 原提示、同一真实语音前 30 秒 FLAC | OTHER，无候选 |
| 原提示、同一真实语音前 120 秒 WAV | OTHER，无候选 |
| 原提示、完整 20 分钟 FLAC | OTHER，无候选 |
| 简明逐字转录提示、完整 20 分钟 MP3 | OTHER，无候选 |
| 同一完整 MP3 与提示，显式 low 思考档 | OTHER，无候选，thoughtsTokenCount 为 0 |

最后一组完全相同的音频及提示，通过 `gemini-pro-agent` 返回 STOP、3,317 字符、76 条有效话轮，最大时间戳 18:25。该响应直接复用于来源缓存，不重复请求。Pro 未按要求输出时间戳方括号，程序仅补括号，另存原文；不重写文字、说话人或时间值。

确定的故障阶段是上游业务响应：网络、鉴权和模型路由均已通过；CPA 原生转换保留 inlineData。HTTP 200 不代表转录成功，必须检查候选、finishReason 和时间。格式转换未稳定修复，不能把 MP3 格式或录音内容违规当成确定原因。Flash 的上游只给出 OTHER 及通用过滤说明，没有暴露具体规则；同一完整音频在 Pro 成功，说明现有系统能够完成 Gemini 音频转录。相关依据：[当前 CPA 原生转换实现](https://github.com/router-for-me/CLIProxyAPI/blob/54946fa/internal/translator/antigravity/gemini/antigravity_gemini_request.go)、[Google 官方音频接口与格式说明](https://ai.google.dev/gemini-api/docs/generate-content/audio)。

按用户要求开放现有 CPA 的 6 个非图像 Gemini 候选，配置热加载生效，模型接口已确认 8 个 Gemini 名称。只移除这 6 项 Antigravity 模型隐藏规则，其余配置逐字段比较保持一致；未重启容器。原配置私有备份为 `source-backups/20261009-plaud-gemini-repair/cpa-config.yaml.before-model-open`。

新增候选逐个收到同一份完整 20 分钟 MP3 和相同提示，结果如下。表中“通过”仅表示有 STOP 文字及合法时间，并非人工准确率评估。

| 模型 | 完整音频测试 | 耗时 |
| --- | --- | --- |
| gemini-3.7-flash-high | OTHER，无候选 | 17.42 秒 |
| gemini-3.6-flash-high | 通过，142 条话轮 | 31.27 秒 |
| gemini-3.5-flash-lite | STOP，但未提供符合格式的时间戳，隔离 | 41.75 秒 |
| gemini-3-flash | 通过，103 条话轮 | 49.57 秒 |
| gemini-3.1-flash-lite | 通过，149 条话轮 | 18.83 秒 |
| gemini-3.1-pro-low | 通过，71 条话轮 | 106.22 秒 |

Pro 临时补跑已恢复 10 个有效块，包括完整 47 分 56 秒短录音；长录音 b008 出现 1 处倒序时间，拒绝成为有效来源。该原文、诊断和失败哨兵单独保留，未排序、裁剪或缩放时间来放宽校验。正式配置随后恢复原 `gemini-3-flash` 路由，继续处理缺失的 8 块。

Hermes 身份、密钥、完整音频块、Groq/SenseVoice 缓存及历史失败哨兵保留。原生实现摘要加入运行及请求身份。完整 promptFeedback、候选数、结束原因、用量和时间校验写入 `gemini-response-diagnostic.json`；异常响应不生成成功摘要或可用转录。补跑短录音的手动辅助入口曾因缺少 PYTHONPATH 在本地退出，确认未发出网络请求后保留该记录并修正路径；正式作业入口无此问题。

本地验证通过：时间括号补齐的幂等性与原文字保留；OTHER、MAX_TOKENS、越界、倒序、无时间戳均隔离；原完整录音与尾块覆盖、缓存和单次融合/摘要门禁保持。

实际补跑结果：18 个完整块均已具备三源结果，保留 10 个通过校验的 Pro 块，余下 8 个由恢复开放的原 3 Flash 补齐；两条录音的 Gemini 正文均已从生产内容接口读到，分别为 6,082 和 69,105 字符。

首次正式融合收到 STOP 响应并保存了 73,961 字符原文，但旧校验仅查找 `[MM:SS]`，将模型使用的 `**HH:MM:SS Speaker ...**` 误判为缺少时间戳。修正为按每条录音识别正文话轮，检查时间分量、范围和顺序；标题的日期时间不能冒充话轮。另验证全部 18 个块标题的编号、起止范围和尾块覆盖。原文中的一行整段时长说明由源录音元数据校正，话轮时间、文字和匿名说话人保持。

复用同次保存的响应恢复正式稿，新增融合请求为 0；保留原失败状态副本、原始响应及 SHA-256。恢复记录明确原请求用量未保存，不编造用量。执行器实现更新后，同一来源、参数和模型的已完成日期继续复用原运行及摘要，避免再次触发每日融合门禁。

最终验收（20:18，Asia/Shanghai）：

- 原 Hermes 作业于 20:16:54 成功执行，last_status=ok、last_error=null，仍启用，下一次为 2026-10-10 00:00。默认 Gemini 模型为恢复开放的 `gemini-3-flash`。
- 2026-10-08 两条录音、18 块处理状态为 complete；正式融合日报为 74,110 字符，正式每日摘要为 1,999 字符。运行目录为 `daily-v3/runs/2026-10-08/3602d092230ecc1f2f63`。
- 完整分源稿及正式结果已入库。两条生产 HTTPS 内容接口均为 200，transcript_engine=three_source_fusion、transcription_status=complete、summary_status=complete、processing.status=complete。短/长录音融合正文分别为 6,520 / 67,590 字符，三路来源均 complete。摘要明确 scope=day。
- 现有已连接 MCP get_data_record 实际读取到完整三源融合正文及 1,999 字符正式摘要，状态同为 complete。
- 原采集服务 active、CRM healthy、CPA running；47 个常驻容器启动登记检查无缺失、额外运行或计划内停止。CPA 容器未重启，身份、密钥、卷和其他渠道保持。
- 本地 smoke 验证了时分秒/加粗话轮识别、真实时间边界、倒序/身份拒绝，以及执行器代码更新后的完成稿复用；git diff --check 通过。仅做来源和格式校验，不声称人工核听准确率评估。
