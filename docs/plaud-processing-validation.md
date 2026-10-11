# Plaud 转录、日报与摘要迁移验收

日期：2026-10-09；完成核查时间：18:38（Asia/Shanghai）。

正式处理源码为 `processors/plaud`，入口为 `agents/nas/plaud-process.py` / `agents/nas/plaud-daily.sh`。原 Hermes Lingjun 作业 `58d4a4c46d49` 继续启用，保留 `*/30 0-7 * * *`、no-agent 模式与本地交付；工作目录改为当前仓库，原 `/home/yuwk/cron/model/plaud-daily.sh` 转发至新入口。下一次计划为 2026-10-10 00:00。原 Hermes 身份、Plaud/Groq/CPA 凭据、模型、业务数据库和缓存保留。

私有配置为 `~/.config/personal-data-hub/plaud-processing.yaml` 及 `plaud-processing-base.yaml`，只增加运行账户所需的配置读取权限。回退配置、原作业清单、包装脚本和 Compose 副本位于仓库外 `source-backups/20261009-plaud-processing`。源码仍在当前工作区，未声称已发布远端提交。

生产 API 镜像为 `local/personal-data-hub:plaud-processing-20261009`，摘要为 `sha256:ca4b000134e3184c612256f2ab2e13be9bce703130ec59744e2574df3c61f545`。正式 mcp Compose 仅修改 crm 的镜像；原 1000:1001、cap_drop ALL、no-new-privileges、端口、卷、网络及 OAuth 身份保持。迁移命令完成，容器 healthy；MCP 部署记录为 `20261009T102157433370`。首次入口验证在容器刚重启时遇到连接拒绝，服务健康后重试通过。

真实处理与入库结果：

- 10 月 8 日两条录音，共 5.799 小时，连续覆盖 18 个块。Groq 与 SenseVoice 各完成 18 个块，短录音 3 块、长录音 15 块。
- 两条完整 Groq 文字稿分别为 5,040 与 65,232 字符；每日摘要草稿为 1,676 字符。完整单源录音日报和每日摘要均已生成、归档并关联录音。
- 旧 `gemini-3-flash` 路由不存在；当前可用模型名更新为 `gemini-3.8-flash-high`，音频使用既有 CPA 的原生 Gemini 接口。实际录音被上游 `blockReason=OTHER` 过滤拒绝，来源状态保持 `source_failed_no_retry`。没有用缺失来源冒充三源融合，日报及摘要明确标 `draft`。
- 18:35 经原 Hermes 官方 Cron 入口实跑，新入口成功执行并如实记录 Gemini 失败。重复执行新增请求身份为 0、已有请求状态修改为 0，已完成转录及摘要均复用缓存。
- 原 25 条录音保留；4 条历史筛选片段转录另标 `source_partial`。归档新增可查询类型为 `recording_transcript`（8 条）、`recording_daily_report`（1 条）、`recording_summary`（1 条）及 `recording_processing_status`（1 条）。采集成功状态与业务处理失败状态分别保存。

接口验证：

- `GET /api/v1/recordings/{record_id}/content` 对两条真实录音均返回 HTTP 200，含完整分源文字、摘要、每日范围、关联日报及真实处理状态；未授权访问返回 401。
- 现有连接的 MCP `get_data_record` 已实际读到新增文字与摘要。新只读工具 `get_recording_content` 的注册、只读标记和真实归档结果读取通过 FastMCP 验证；生产 MCP initialize 的匿名拒绝与 OAuth 发现通过平台探测。
- 默认 25 条录音列表为 13,258 字节，不携带 raw、normalized 或附件正文，长文字从详情读取。
- 合成音频验证通过：1,225 秒完整覆盖、25 秒尾块、缓存、单次融合/摘要门禁，以及缺失 Gemini 时只发布明确标记的草稿。内容接口验证通过：缺块、错哈希、历史/草稿/完整稿区分、日报关联、幂等归档和鉴权。
- 既有统一采集服务 active/running；启动检查 47 个常驻容器，missing、active_unplanned、stopped_planned 均为空。

上述为 18:38 的迁移验收时点。随后已按用户要求排查并重新开放隐藏的 Gemini 音频模型，恢复原 3 Flash 处理，完成 18 块三源转录；后续正式稿、摘要与接口验收见 `docs/plaud-gemini-diagnostics.md`。来源校验和程序冒烟不等同人工转写准确率评估。
