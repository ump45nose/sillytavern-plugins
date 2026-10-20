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
2. 日报通过 CRM 现有本机 HTTP API 读取互动与正文；分页、联系人解析与时间窗口由程序完成，不依赖 MCP/OAuth，不新增聊天镜像。
3. config validate 与隔离状态的 daily prepare 成功，证据与缺失项符合真实来源。保留生产冻结材料及 pending checkpoint。
4. 只做与缺陷相称的定向验证，记录源码/部署差异、备份与未验证的真实发送。

## 进度

- [x] 读取昨日迁移计划、部署规范和调度/执行/网关日志。
- [x] 定位并恢复投递连接。
- [x] 修复迁移后的 CRM 实际接入与 skill 部署遗漏。
- [x] 验证、部署、提交检查点并报告。

## 修复与接入决定

- 经三个已有节点对 Telegram 的定向连接测试，原手动美国节点超时，日本节点对该目标失败，新加坡 Vless 节点成功。只将“社交通信”和“国际服务”两个 selector 切到该节点；其他组、规则、核心配置不改，未重启网关。原 selector 备份在 `/home/yuwk/.local/state/incident-diagnostics/2026-10-20-hermes-daily/proxy-selection-before.json`；Mihomo 原有 selector cache 已更新。
- 实际 Hermes 身份经同一代理调用 Telegram getMe/getChat 均 HTTP 200、ok=true；原网关自动重连，11:23:03 确认 getUpdates 正常。Google Calendar/Tasks 只读输入成功（2 条已完成任务），邮件四账户输入成功（10 条筛选结果）。这些探测不写生产输入文件、不发送消息。
- 旧 CRM MCP 上游 refresh 返回 invalid_grant。用户指出本地已有 API；应删除日报对该 MCP 的依赖，不要求用户重授权。保持其他 Hermes MCP 配置，不修改其 OAuth 状态。
- 健康/账单本来直接读本机 Records API。Skysight 当前为本机 SFTP 发布归档，没有独立 HTTP 容器/服务；源码 README 亦声明不增加 HTTP 服务，继续直接读取归档，不新增转发层。
- 新增 `reviewctl crm read --date` 只读命令，复用既有 API 和只读 token：完整读取列表分页、联系人与正文，按 CRM 北京时间消息格式裁切跨日/跨截止点内容，保留多行消息。原接口直接提供完整正文，无需 MCP 的分段工具；CLI 不初始化状态库、不复制聊天正文到复盘数据库。读取失败返回错误，不假装零条。
- 日报 prompt 与 canonical/live skill 同步改用上述命令；保留原 Skysight 和近期已确认日报的有效交互说明。初次仅更新 skill 的版本已由本轮最终 API 指引替代。
- 私有 skill 备份、隔离 SQLite 与诊断材料在 profile `cron/migration-backups/daily-repair-20261020/`。隔离窗口实读 2026-10-19 得到 Skysight 22、健康/账单/CRM/Git 各一份证据；昨日邮件/Google 输入未生成如实记录缺失，未改动生产冻结材料或 pending checkpoint。

## 最终验收

- 定向 HTTP 测试共 5 项通过，覆盖分页/认证、排除截止后的交互、完整正文超过列表预览、跨日/截止点和多行消息，以及 HTTP 失败不能变成零条。未扩大测试范围。
- 集成 `d1ffbab` 到主线后，实际 Hermes 身份运行正式 `reviewctl crm read --date 2026-10-19`，成功读取 15 段对话、8 位联系人、4356 字符。特意使用空 MCP HOME 和不存在的测试状态库：无任何 MCP 凭据/缓存产生，状态库未创建，证明正文读取不依赖 MCP/OAuth，也不落库。
- 正式源码链接已生效；live skill 与 canonical 字节一致，日报任务 prompt 来自 CronPlanner，746 字符，已去掉旧 CRM 工具指引。原 ID、enabled、21:30 调度和投递目标保持；Plaud 作业仍暂停。
- 最终 config validate 通过；网关自 11:23:03 恢复后至 11:33 未再出现 Telegram 连接错误。历史 delivery_failed/error 留作真实历史，未伪造成功、未推进 pending checkpoint。
- 部署后启动检查无新增差异，仍只有已有 tailscale 缺失及 ai-resource-center 未登记，无 stopped_planned。
- 没有手工运行模型日报或实际补发消息。今晚 21:30 的完整生成与实际投递尚未发生，不能把只读协议验证宣称为实投成功。

## 用户要求的昨日手工验收（2026-10-20 11:36–11:43）

- 用户要求“手动启动脚本拉下昨天的测试下”，显式测试日期为 2026-10-19。复制 SQLite 到私有测试目录，并仅删除副本中的同日会话，实际运行正式 CLI `daily prepare --date 2026-10-19 --dry-run` 与 `crm read --date 2026-10-19`，确认 mode=dry-run，测试库也没有冻结该会话。生产状态、调度和 pending checkpoint 保持。
- Google 使用现有脚本的历史日期参数，得到 Tasks 5 条、Calendar 0 条，无错误。邮件复用正式 transport、四账户和筛选策略，仅在手工查询中显式绑定 since/before 为昨天自然日，得到 0 条、无错误；这与摘要文件缺失区分开。两类输入只写测试目录。Skysight、健康、账单、Git、CRM 及已有目标/确认记录正常进入新材料。
- 正式 CRM CLI 得到 15 段、8 位联系人、4356 字符。Hermes 使用同一日报 model=grok-4.7、provider=custom:cpa-local 对已实际读取的材料生成本地测试稿，1 次主模型调用、0 次工具调用，首行和日期正确，8 位联系人均出现在结果中。
- 主模型耗时 227.3 秒，输入 37964 / 输出 15960 token，正文 9377 字符，正常 stop。实际正文生成通过；CLI 的辅助会话标题请求曾返回 401，不影响主模型报告生成，未将该辅助请求宣称为通过。
- 完整测试产物在 `/vol2/1000/Docker/personal-review/artifacts/manual/2026-10-19-test-20261020-113644/`，用户可读的结果为 `report.md`；原始材料、CRM 返回、输入摘要、stdout/stderr 和状态回执均在同一私有目录。它们不进入 Git。
- 没有手工发送消息、发布终稿或确认 checkpoint。本次验证了真实读取与同模型编辑，没有执行 scheduler 的实际 Telegram 投递。
