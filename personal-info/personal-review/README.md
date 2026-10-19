# Personal Review

Hermes 日报、周报、阶段与年度复盘的业务程序。用户确认内容保留在既有 Memos 账本，SQLite 保存本应用的会话、投递、证据与工作状态。

## 数据输入

- CRM：直接通过独立 HTTP API 分页读取互动计数；日报 Agent 使用 list_interactions/get_interaction/get_person，不复制聊天库。
- 健康与账单：直接使用 Personal Records API。
- 邮件：现有邮件应用的原生 MCP，保留主题筛选和只读行为；失败明确报错，不生成零邮件快照。
- Skysight：读取独立同步归档的发布清单和对象，每台设备分别采用完整 6h 摘要或 10min 摘要；来源未同步时明确报告。NAS 通过固定只读命令访问私有归档，不改变原始文件权限。
- Git、日历、Tasks、Memos：沿用既有消费者接入，不经过 Hub。

## 运行与部署

源码入口为 `/vol1/1000/Code/personal-info/personal-review`。运行目录 `/vol2/1000/Docker/personal-review` 保留原配置、数据库、产物和认证，静态源码通过链接提供。NAS 任务代码归 `nas-cron-jobs/hermes`。日期、用户确认流程和现有业务开关保持不变。

`reviewctl config validate` 校验配置，`doctor` 检查运行状态。`daily prepare` 冻结材料，重复运行回放快照；`daily refresh` 显式重新读取来源。`daily prepare --dry-run` 不冻结材料或提交来源游标。日报终稿仍需用户确认。

`weekly prepare`、`stage prepare-close`、`projections pending`、`attachment pending`、`annual prepare` 保留既有业务。日报投递成功后由独立回执任务提交 checkpoint；投影失败不回退已确认账本。旧 CRM 日快照输入及旧 raw/derived 保留任务已退役。

部署与实际验证记录见聚合仓库 `docs/plans/2026-10-19-hub-retirement.md`。
