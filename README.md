# Personal Review

Hermes 日报、周报、阶段与年度复盘的业务程序。用户确认内容保留在既有 Memos 账本，SQLite 保存本应用的会话、投递、证据与工作状态。

## 数据输入

- CRM：直接通过独立 HTTP API 分页读取互动计数；`reviewctl crm read --date YYYY-MM-DD` 读取正文并按消息时间限定窗口、解析联系人，只输出给日报 Agent，不写入复盘数据库。无需 CRM MCP/OAuth。
- 健康与账单：直接使用 Personal Records API。
- 邮件：现有邮件应用的原生 MCP，保留主题筛选和只读行为；失败明确报错，不生成零邮件快照。
- Skysight：读取独立同步归档的发布清单和对象，每台设备分别采用完整 6h 摘要或 10min 摘要；来源未同步时明确报告。NAS 通过固定只读命令访问私有归档，不改变原始文件权限。
- Git、日历、Tasks、Memos：沿用既有消费者接入，不经过 Hub。

## 运行与部署

源码入口为 `/vol1/1000/Code/personal-info/personal-review`。运行目录 `/vol2/1000/Docker/personal-review` 保留原配置、数据库、产物和认证，静态源码通过链接提供。NAS 任务代码归 `nas-cron-jobs/hermes`。日期、用户确认流程和现有业务开关保持不变。

阶段 5 来源改动在聚合 worktree `codex/phase5-review-http-20261021` 开发，按用户确认发布到私有 `ump45nose/personal-review`。发布后的独立源码 checkout 为 `/home/yuwk/src/personal-review`；运行目录的静态源码链接使用该 checkout，配置、数据库、Memos 凭据和产物不迁移。聚合 main 的其他人修改不代提交或合并。

`reviewctl serve --host 192.168.31.201 --port 18191 --token-hash-file <私有哈希文件>` 提供 `/v1/reviews`、会话详情与 preview、`/v1/stage`；`/healthz` 无认证。原始 Bearer 只在 Hub 私有环境中，来源只读取 SHA-256 哈希。模板见 `deploy/personal-review.service`；HTTP 不输出访问日志、正文或上游错误。

预览直接调用既有 `finalize(..., dry_run=True)`。旧周报的展示材料来自冻结 evidence，不重新采集或修改会话。阶段读取不冻结结案模板；评论读取失败通过 `X-Review-Partial: true` 标记，正文中不增加内部状态字段。投递正文只读取匹配成功执行输出中的 Response，失败或缺失为 null。

验证：在本目录使用现有 Hermes Python 执行 `python -m pytest -q`。阶段 5 首轮 71 项测试通过。修正了迁移后脚本转发器在测试 import 时意外运行 CLI 的问题（直接执行方式保持），并把旧财务 golden fixture 更新到当前 Personal Records 的 totals 列表；未改变生成或 cron 业务规则。

`reviewctl config validate` 校验配置，`doctor` 检查运行状态。`daily prepare` 冻结材料，重复运行回放快照；`daily refresh` 显式重新读取来源。`daily prepare --dry-run` 不冻结材料或提交来源游标。日报终稿仍需用户确认。

`weekly prepare`、`stage prepare-close`、`projections pending`、`attachment pending`、`annual prepare` 保留既有业务。日报投递成功后由独立回执任务提交 checkpoint；投影失败不回退已确认账本。旧 CRM 日快照输入及旧 raw/derived 保留任务已退役。

部署与实际验证记录见聚合仓库 `docs/plans/2026-10-19-hub-retirement.md`。

更新日报接入时，同步部署 `deploy/skill/personal-review/SKILL.md` 到 Lingjun profile 的 `skills/lifestyle/personal-review/SKILL.md`，并更新现有日报任务的 prompt；静态源码链接更新不会自动替换 profile 中的 skill。保留任务 ID、schedule、投递 topic、执行历史和暂停状态。`config validate`、`doctor` 不能替代来源实读或实际投递验证。
