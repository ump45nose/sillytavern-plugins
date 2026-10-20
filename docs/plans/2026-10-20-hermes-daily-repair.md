# Hermes 日报 cron 故障修复（2026-10-20）

## 范围与决定

恢复 Lingjun 日报的真实读取与投递链路；业务逻辑归 personal-review，调度包装归 nas-cron-jobs，私有 profile/认证保持仓库外。沿用原任务 ID、时间、投递 topic 和暂停状态。未经真实投递不确认 checkpoint；不手工发送补报、不修改历史事实、不恢复 Hub。

## 当前证据

- 2026-10-19 21:30 两个既有日报任务正常触发并生成内容；21:32 Telegram live adapter 与 standalone 路径均连接失败，last_status=delivery_failed。21:35 ack 因投递未成功而拒绝推进，符合保护要求。
- 该次失败早于 22 时的 Hub 输入迁移；不能认定由迁移引起。当前网关仍反复 Telegram ConnectError。
- 宿主代理 7890 可监听，但到 Telegram/Google TLS 超时；ShellCrash 日志记录所选节点连接超时。工具与网关处于同一网络命名空间。
- 旧日报运行调用 get_daily_chat_records 且 CRM OAuth refresh 401；部署后的 personal-review skill 仍提及旧工具，源版本与 live skill 有差异。当前任务 prompt 已换新工具，实际 MCP 入口及认证待验证。

## 验收

1. 实际 Hermes 身份、同一代理路径完成 Telegram getMe/getChat 只读协议验证，并核对网关恢复。
2. 日报实际使用的 CRM 工具可发现并读取当日互动及正文；不依赖旧 Hub、无浏览器交互。
3. config validate 与隔离状态的 daily prepare 成功，证据与缺失项符合真实来源。保留生产冻结材料及 pending checkpoint。
4. 只做与缺陷相称的定向验证，记录源码/部署差异、备份与未验证的真实发送。

## 进度

- [x] 读取昨日迁移计划、部署规范和调度/执行/网关日志。
- [ ] 定位并恢复投递连接。
- [ ] 修复迁移后的 CRM 实际接入与 skill 部署遗漏。
- [ ] 验证、部署、提交检查点并报告。
