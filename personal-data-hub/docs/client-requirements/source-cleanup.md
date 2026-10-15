# 来源清理后的 Mac 客户端调整

服务端清理在独立分支，尚未集成部署。Mac 修改不阻塞本轮服务端代码清理；服务端部署时再联调。当前应用源码未被本轮修改。

## 来源和入口

保留微信/联系人、电脑历史、Plaud、健康、账单和网络流量。移除 Hub 来源选择中的 Mem0、Hermes、Memos、GitHub、Emby、Navidrome、Google Calendar/Tasks、Token Monitor 和邮件，以及依赖这些镜像的卡片、趋势、空状态和内容类型入口。

原系统直连接入属于后续需求，不在此次删除中建设。Google 本机编辑如需继续使用，应作为原系统直连能力独立管理，不能依赖已移除的 Hub 日历/任务镜像。

## HTTP 合同变化

- `GET /api/v1/dashboard` 模块只支持 `health,social,activity,recordings,reports,finance,network`；默认 `health,social`。
- `GET /api/v1/trends` 同上，默认 `health,social,network`；删除 `agenda,usage,notes,mail,git`。
- `GET /api/v1/timeline` 默认 `social,activity,recordings,reports`；技术记录仍可显式查询。
- `/api/v1/sources`、`/api/v1/kinds`、原件列表和阅读列表/搜索只返回保留范围。原 ID 的历史详情与附件读取保留。
- 入库来源需在保留配置中注册；不支持的来源或类型返回 422。
- 阅读和分析入口不新增模型能力；既有微信提炼继续暂停。

## MCP 变化

删除 `get_daily_memos_report` 及 `crm.daily_memos_report.ready` 的生产和订阅发现。日报正文与事件读取工具的 `source` 仅支持 `codex_skylight`。原聊天/健康/财务的每日数据读取和聊天事件保持。

删除界面功能时同步删除控件状态、类型定义、请求、错误提示和无用配置。历史数据物理删除不属于客户端工作。
