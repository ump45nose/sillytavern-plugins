# NAS MCP Events 部署记录（2026-10-05）

## 当前状态

NAS 服务端已经部署并通过本机／公网健康与权限检查。CRM、邮件原连接的真实只读调用成功。四个接收邮箱均完成实际 IMAP 基线；钉钉待办、审批在新容器内也完成真实只读基线。

ChatGPT 推送订阅尚未建立：当前可操作的浏览器没有登录；事件源发现仍只返回既有 GitHub 和 Gmail，需要刷新原 CRM、邮件原生 MCP 连接的发现，并注册“用量统计”后创建用户订阅。服务已运行不代表 ChatGPT 已开始推送。

## 部署与版本

| 组件 | 版本／提交 | 生产状态 |
|---|---|---|
| 公共事件运行时 | 0.1.4，f9281abd5db0bf0614aa817832d2440e4b7ae57b，v0.1.4 | 已注入三业务镜像 |
| CRM | 0.1.2，6e2c95f060338048b67e750ad08cc53de9bb28fc | 原容器身份、数据卷、OAuth 和域名保留 |
| 邮件适配 | 0.1.1，0ae3f06052520f1f36f9713a8128abf936e70419 | 四账号接收基线成功；原数据与 OAuth 卷保留 |
| 钉钉事件包 | 0.1.1，59f91c009207528a4183e6d6db242f6ccf4117cd | 新统计进程加载；原 MCPHub 服务保留 |
| 用量统计 | 0.1.0，业务 d564b991d6355a9a6cfaf6d6e17ddb79b52d8094，构建流程 59cfbe3f174498d9adb059c8f33c9013aa242d49 | 独立 MCP，已有 Tunnel／Authelia 共用设施 |

入口：CRM `https://crm-home.172906573.xyz/mcp`；邮件 `https://email-home.172906573.xyz/mcp`；用量统计 `https://usage-home.172906573.xyz/mcp`。

CRM 镜像 ID：`sha256:cefda7173690682f2e6744db5e25f3c8debb98bf754657cc4601fde20ef0bf62`。

邮件镜像 ID：`sha256:5817319b3a7d50fa847d125d9aaebb3498a3ca5eef2f5b00b5dcb90f5e53c180`。

统计镜像 ID：`sha256:fc4ee34692b53c6d59256e6108eb5395def95c8877c8de2ba90814bbef10de3a`。

三镜像均离线安装已校验 wheel，并通过依赖一致性检查。原工作区其他未提交修改保留；构建使用精确提交导出的源码。每份源码、wheel、基础镜像及最终镜像的摘要保存在仓库外私有发布记录。

## 事件行为

| 事件 | 触发与内容 |
|---|---|
| crm.daily_chat.ready | Asia/Taipei 每日 23:00；当天零点至截止时的已采集聊天原文。固定报告、分页；晚到记录和 23 点后内容在后续报告补充。 |
| email.important_received | 4 个现有接收账号；120 秒只读检测，启动基线之后的新信；重要性规则、去重、限频。默认最多 6 条／小时，模糊候选最多 1 条／小时；重要邮件超额保留游标等待，不越过。 |
| dingtalk.todo.assigned | 新待办或重新出现的待办。 |
| dingtalk.todo.changed | 标题、截止时间、优先级变化。 |
| dingtalk.todo.due | 进入未来 24 小时截止范围，或首次逾期。 |
| dingtalk.approval.pending | 当前企业用户的新待审批事项。 |
| usage.daily_ready | Asia/Taipei 每日 23:00；当天 Token Monitor 与 ShellCrash 数据合为一份报告。 |

钉钉每 300 秒只读检测，首次建立基线不回放历史。当前待办基线 2 条、审批 0 条、待推事件 0 条。日历返回缺少事件 ID 的异常结构，保持禁用并提供诊断。

CRM 仅有摘要、未采集原文的记录明确标记缺失；不能恢复入库前已被去除的外围空白。统计显示采集缺口、设备离线和额度未知，模型／工具／设备是同一用量的不同分类；估算成本与实际订阅付款分开，当前订阅列表未配置。

## 验证

公共协议与只读挂载 24 项测试通过；CRM 15 项、邮件 28 项、钉钉 9 项针对性测试通过；统计 11 项日期与数据边界检查通过。覆盖原 MCP 协议兼容、认证与主体隔离、签名、订阅保存、重试、报告分页和去重、邮件超长头隔离及账号公平轮转。

生产实际验证：原 CRM 查询当日摘要、邮件账号发现成功；四个邮箱消费游标完成基线，无历史邮件发布；统计 API 与两个文件来源可读；钉钉待办和审批状态均 ready。所有生产 MCP 匿名请求返回 401，公网 TLS 保持验证。没有创建测试回调或发送测试事件。

## 维护与回退

CRM／邮件此次切换仅更换业务镜像并合并事件环境变量，原卷、网络、命令、运行用户及认证字段保持一致。私有发布目录是 `/vol2/1000/Docker/stacks/mcp-platform/runtime/_mcp-events/releases/20261005-events-0.1.4`，各 `switch/<crm|email>/journal.json` 记录完整事务。需要回退本次 overlay 时使用同目录上级的 `switch_overlay.py --release <发布目录> rollback <crm|email>`；保留当前业务数据与 OAuth，不恢复旧数据快照。

统计使用 `usage-data` 持久卷、三个只读绑定目录及独立私有秘密文件。清单为 `deployment_mode: existing`：业务仓库准备固定 wheel／基础镜像的离线构建和 Compose；公共 mcpctl 协调认证、Tunnel 和 DNS。首次独立 OAuth 客户端使用公共 prepare_auth_change 显式传入私有 env 后创建；既有客户端后续由 mcpctl 正常协调。首次未提供 env 的入口尝试在任何共享配置改变前停止，回退记录 complete；之后独立客户端与公开入口均成功。

统计私有 bootstrap 记录、构建记录及入口事务位于 `/vol2/1000/Docker/stacks/mcp-platform/runtime/usage-monitor-mcp`。源仓为私有 `ump45nose/usage-monitor-mcp`。原 CRM、邮件 App ID 沿用既有原生连接；不用 Plugin Creator 重新包装。
