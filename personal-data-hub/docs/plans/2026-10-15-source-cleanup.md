# 来源与镜像链路清理

> 2026-10-15 合并更新：用户已明确要求合并；本任务与另一分支已集成到 main，生产部署单独处理。下文的原未集成边界为当时记录，最终结果见 [合并记录](2026-10-15-integration.md)。

## 范围

保留 CRM/微信、Skysight 原始片段与摘要、Plaud、Health、AutoAccounting、NAS/Mac 网络流量。移除 Mem0、Hermes 报告、Memos、GitHub、Emby、Navidrome、Google Calendar/Tasks、Token Monitor 和邮件在 Hub 内的采集、镜像加工、来源展示与专属接口。原系统的存储、接口、独立任务与凭据保持；Mac 客户端由用户在 Mac 修改，本轮提供接口变更清单。

历史镜像数据、附件、原有任务与水位保留，不执行物理删除；停止来源不再入库、被调度或进入重建。已有历史记录可凭 ID 读取，默认列表和统计只展示保留范围。CRM、Skysight、Plaud、健康、账单和网络的结构重设计留到下一轮。

## 关键决定

- 使用一个聚合独立 worktree：`personal-data-hub/.worktree/source-cleanup-20261015`，分支 `codex/hub-source-cleanup-20261015`。发现 `hub-p1-20261015` 已有并行修改，不覆盖或合并其代码。
- 继承主工作区已有性能止血差异，仅作为比较基线，保存至公共 Git 目录 `task-checkpoints/hub-source-cleanup-20261015/inherited-baseline.patch`；本轮修改单独保存检查点。
- 删除已退出来源的实现和专用依赖；用保留来源的数据类型约束通用入库、查询和加工，历史队列不得因恢复后台而被继续处理。
- 移除 Hub 对 Memos 日报的读取与事件接入；保留 Skysight 摘要查询和现有 CRM/健康/财务日报事件。
- 保留独立 Token Monitor/Usage Monitor 服务，不在本轮删除其业务项目；Hub 移除对其归档和依赖。
- 保持轮询和加工暂停，不启动全库重建，不清空生产数据库。主工作区有未提交且并行改动，满足集成条件前不覆盖主工作区、不部署混合版本。

## 验收

集中验证删除来源无法通过配置、CLI 或通用入库重建；旧任务不再领取，旧原件不参与默认列表与加工；保留来源的推送、文件确认、网络提交与查询仍可用。使用隔离数据和既有受影响检查；不调用上游接口、模型或重放真实消息。

## 进度

- 已核对代码、当前部署记录、并行 P1 工作区和止血基线。
- 实现完成：删除来源适配器、专属加工器、邮件桥接、Google 隔离导出及其错误分支；移除 Hub 对 Usage Monitor 的运行依赖和构建步骤。
- 配置、注册与通用入库限定保留适配器及记录类型；默认原件/阅读列表、统计、展示和任务领取排除退出来源。旧原件、附件、版本、任务、水位及按 ID 读取保留。
- CRM 的 Memos 日报工具、配置字段及事件注册已删除，Skysight 和聊天/健康/财务既有路径保留。Mac 源码未改，调整需求在 `docs/client-requirements/source-cleanup.md`。
- 更新 README、当前架构/开发顺序、接入与部署说明；过往验收明确标为历史，删除 Git/Emby/Navidrome 接入说明和 M4 客户端增量清单。

## 集中验证结果

- 来源清理 3 项检查通过：旧配置拒绝、通用入库不能伪装旧类型、历史原件与任务保留但不再列出/领取/回填、六类来源入库和只读边界。
- 隔离 PostgreSQL 6 项既有回归通过：更新/删除 fencing、周期去重不重写、回填跳过已覆盖正文、积压遵守间隔、发布让位。发现删除成员 SQL 被筛选条件误带入关联表，修正后只复查该项，通过且无该警告。
- Skysight/MCP 日报工具与冻结事件两项、微信原文补齐去重一项、Mac 网络来源隔离及乱序累计一项通过。
- 既有 stage2、display、query-status、daily-push 四条冒烟通过，覆盖账单、健康、附件、分页、正文、历史异常和 HTTP/MCP 鉴权。日报冒烟中的 PermissionError 是预期的越权拒绝。未调用真实上游、模型或重放真实消息。
- Hub 和 CRM wheel 均构建成功。依赖锁只移除根包对 usage-monitor-mcp 的依赖；该独立应用仍保留为 workspace 项目。

## 配置候选与运行边界

私有候选目录：`/home/yuwk/.config/personal-data-hub/releases/source-cleanup-20261015-162020/`。宿主从 18 个来源条目收窄到 7 个，容器从 16 个收窄到 7 个；除来源条目外的配置及所有保留来源设置逐值一致，候选权限 0600，加工仍关闭。脚本不替换在用配置。

实际复查正式容器仍是 `local/personal-data-hub:0.4.9-performance-relief-20261013`、1000:1001、healthy；轮询 service disabled/inactive。本轮没有生产部署、正式数据删除或后台恢复，因此尚未验证清理版本的生产联调和吞吐。

主工作区和 P1 分支仍有未提交修改，按用户集成约定不覆盖、不合并和部署混合代码。清理差异独立保存在公共 Git 目录 `task-checkpoints/hub-source-cleanup-20261015/source-cleanup.patch`；继承差异单独保存，未把归属不明的改动提交。下一步先解决主工作区归并，再将本清理与 P1 差异集成，并配套替换两个私有候选配置。
