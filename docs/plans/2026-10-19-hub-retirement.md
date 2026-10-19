# 日报输入迁移与 Hub 退役

## 范围与决定

- 用户授权：日报输入迁至各独立应用后，删除 Hub；不再建设统一数据或读取层，网络不在本轮范围。
- 独立聚合 worktree `codex/hub-retirement-20261019`，起点 main `5516041`。主树另有 benefits 修改与 personal-info 入口，不覆盖、不代提交。
- 整合已确认的 personal-records/Plaud 分支源码与登记；CRM、Skysight 以各独立仓库当前源码为准。
- CRM 日报直接读取独立 CRM；邮件直接调用现有邮件 MCP；Health/账单沿用 Records API；Skysight 读取独立同步归档，业务日期处理等待用户选择。
- 运行中的 personal-review 程序迁至 personal-info，沿用既有数据库、状态、日报时间和交互行为。只修改受影响的日报提示词、包装和配置。
- 删除 Hub 采集/存储/加工/API/客户端等源码与在用登记，停用旧容器和巡检；保存一次退役备份，不删除共享 PostgreSQL、独立应用数据、认证或历史备份。
- Plaud 切换独立 CLI 包装，保持既有暂停状态；人工核听/OAuth 与恢复任务不在本轮擅自完成。

## 验收

- 以 Hermes 真实身份读取 CRM、邮件、Records、Skysight；验证日期、分页及失败直报，不发送消息、不提交日报、不触发转录。
- 日报/周报资料生成可运行，输入不再引用 Hub 包、旧工具、容器或旧 Skysight 目录。
- 源码/部署/任务提示词的活动依赖扫描通过；独立应用真实健康和只读接口保持可用。
- Hub 容器和旧任务已退出，正式 Compose、平台登记、开机清单与 STACKS 一致；执行适用启动检查并记录既有差异。
- 完成相关的少量行为验证与本地提交。集成前检查最新主线和改动归属，主工作树不干净时不覆盖他人修改。

## 进度

- [x] 读取运行现状与相关维护技能，确认旧 CRM CLI、邮件桥接和 Skysight 日报输入仍有残留。
- [x] 建立隔离工作区和计划。
- [ ] 整合独立应用源码、迁出复盘程序。
- [ ] 修改并验证日报输入。
- [ ] 部署消费者、退役 Hub 和清理活动登记。
- [ ] 集中验收、提交与集成检查。

## 运行检查点（22:15，Asia/Shanghai）

- 已合并 Records/Plaud 已确认分支历史；CRM 从 `/home/yuwk/.config/personal-crm/source` 本机 Git 导入 subtree，HEAD 与 GitHub main 的 c8a5c231 一致。GitHub HTTPS Git 失败，未改网络或凭据。
- personal-review 已迁至 personal-info；Code/personal-info 新建本任务的 CRM/review 源码入口，原 Records/Plaud 入口保持。
- CRM 在 daily prepare 时直读 HTTP，不再有每日汇总文件；提示词使用 list_interactions/get_interaction/get_person，移除 Fact/提醒及旧工具。
- 邮件使用现有容器 mcp-platform-email-mcp-1 的原生 MCP stdio，移除 Hub 桥接导入；原生发现 19 工具和 gmail1 单封元数据读取通过。完整邮件输入探测 gmail1 返回工具错误，正在定位；不把它记为全链成功。
- Skysight 实际归档已有当日内容，无需修改 Mac。读取 `/home/yuwk/.codex/skysight-sync/devices/*/manifest.json`，每台设备各自去重 6h/10min；Hermes 实际读取 22 条、两台设备、无告警。保留原归档权限，以唯一受限 sudo 命令调用本机只读 helper；helper 不接受路径或命令。
- NAS 原有 symlink 中有 13 个指向 Hub 的脚本和 ShellCrash 目录，已将所需源码归 NAS；不更改网络采集业务。仍运行的 Usage Monitor 从已确认分支保留至 app-configs/token-monitor/usage-monitor，容器与 Token Monitor 不改。
- Hub 源码已在本分支删除；旧运行容器尚未停。新复盘源码链接和配置已切生产，config validate 与 doctor 均通过，业务数据/认证/日报确认状态不改。
- 已在副本库生成 dry-run 日报，包含 Skysight/健康/财务/Git/CRM 等材料。真实 CRM 当日统计 15 次、8 人。新增 3 项输入行为验证通过；未调用模型或发送消息。
- 旧 CRM 输入、旧 raw retention、Hub 巡检 3 个任务及入口已移除；仅改现有日报任务的 prompt，保留其他任务/暂停状态/执行历史。切换时并行新增的其他任务也完整保留。
- 私有回退：`/vol1/1000/personal-data-hub/source-backups/20261019-hub-retirement-220130`；候选及只读探测在 Hermes 的 `cron/migration-backups/hub-retirement-20261019/candidate`。CRM viewer token 复用至消费者自己的 mcp-tokens/personal-crm-api.token，不输出凭据。
- 待做：邮件错误定位、正式 Compose/开机/平台来源清理和旧容器退出、活动依赖扫描、文档及检查点提交。主树有 benefits 的他人未提交修改，尚未集成。

## 部署完成检查点（22:28，Asia/Shanghai）

- 生产旧 Hub 容器 personal-crm-crm-1 已 stop/rm，未使用卷删除参数；Formal mcp Compose 仅移除该服务及两个未被其他服务引用的卷声明，实体卷保留。宿主与 Dockge 内 config --quiet 均通过，其他服务对象逐字段一致。
- 私有 MCP targets 仅迁移 CRM 与 Usage Monitor source_roots；两项 mcpctl plan 通过。mcpctl doctor 确认 Docker/Compose、Tunnel、Authelia 与 Cloudflare 凭据正常。
- 已移除采集 systemd 单元并 daemon-reload；开机清单由旧 Hub 改为独立 CRM。boot --check 只剩原有 missing=tailscale、active_unplanned=ai-resource-center；没有 stopped_planned，原 personal-crm 未登记差异已消除。
- Hub 退出后，CRM/Records/Plaud /healthz 均 200；Records 健康/账单读取各返回一份证据，无告警。生产复盘 doctor=ok。Plaud CLI 包装已指向独立应用，原暂停状态不变。
- 完整邮件输入仍会受到 Gmail 上游 provider_failure 影响；原生 MCP 单封元数据、正文读取均已成功，但完整任务两次失败，未记为完整采集成功。错误来自独立邮件 provider，不是 Hub 依赖；现在保留服务端安全错误信息，避免只报泛化错误。未修改邮件服务、网络或凭据，也未用旧资料伪造当日成功。
- 代码验证：3 项真实 HTTP/文件行为测试通过；原有 cron 5 项中与删除任务有关的计数断言已调整，删除语言字面和任意长度断言，重新验证失败项通过；其余 4 项此前通过。生产配置及实际副本 material dry-run 通过，没有触发模型或通知。
- 旧 Hub 历史数据库/卷与一次退役备份保留；共享服务和独立应用认证不变。生产状态已按本方案更新 STACKS。
- 尚待：最终提交与主线集成。主线仍有 benefits 的他人修改；按 AGENTS 不覆盖、不隐藏、不代提交。运行源码依赖本任务 worktree，未经后续集成不得删除。
