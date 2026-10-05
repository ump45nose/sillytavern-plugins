# NAS MCP Events 部署记录（2026-10-05）

## 当前状态

NAS 的 CRM、邮件、用量统计三个服务已升级公共运行时 0.1.5，并通过实际版本、依赖、健康及匿名权限检查。CRM、邮件原连接的真实只读调用成功；四个接收邮箱及钉钉待办、审批的既有基线保留。

用户已完成 Google 验证及 ChatGPT 登录。0.1.4 阶段在原生界面刷新 CRM 和邮件后，事件源仍只返回 GitHub、Gmail；0.1.5 部署后，2026-10-05 14:41:52（UTC+8）原生 `list_event_sources` 已实际返回 CRM、邮件，两者的事件 schema 发现及原有业务只读调用均成功。

四项请求中，“CRM 当天聊天记录”“重要新邮件”两项事件订阅已建立并启用。2026-10-05 14:45:30（UTC+8）只读复核：CRM、邮件各有 1 条订阅、1 条有效订阅，均已验证回调，没有未验证的有效订阅；用量统计仍为 0 条。“钉钉待办／审批”“每日用量统计”两项尚未创建；本轮 OAuth 已完成，剩余阻塞是当前会话没有加载用量统计的 7 个工具，尚不能完成要求的实际只读调用验收。该次 14:45:30 复核时，三库待发送、失败及留存业务事件均为 0；没有制造合成业务事件，实际业务事件送达等待自然触发。

“用量统计”原生 App 的 OAuth 已完成：用户完成当前验证后，原详情页显示已连接账户，`automations.list_event_sources` 已返回该 App，事件 schema 发现成功，包含原有 4 个钉钉事件与 `usage.daily_ready`。App ID 保留为 `asdk_app_6ac33f40ad208191a08fbcfe6894796d`，插件 ID 为 `plugin_asdk_app_6ac33f40ad208191a08fbcfe6894796d`，原详情页是 [用量统计](https://chatgpt.com/plugins/plugin_asdk_app_6ac33f40ad208191a08fbcfe6894796d)。

本轮主会话与部署复核代理的新一轮检查均未暴露该 App 的 7 个工具；事件 schema 可发现不替代实际只读工具调用成功。下一步需要在新会话或显式 @ 选中“用量统计”后加载工具，完成要求的实际只读验证，再创建钉钉与每日用量两项事件任务。原 CRM、邮件订阅继续启用，不重复创建。

### 原生客户端与订阅

| 原生连接 | App ID | 事件订阅与状态 |
|---|---|---|
| CRM | `asdk_app_6ac28369423081918d34fa531d15a62d` | “CRM 当天聊天记录”，`crm.daily_chat.ready`；2026-10-05 14:42:43（UTC+8）创建成功并启用；服务端与回调已验证 |
| 邮件 | `asdk_app_6ac285e95d74819193f153ce16dc5640` | “重要新邮件”，`email.important_received`；2026-10-05 14:43:07（UTC+8）创建成功并启用；服务端与回调已验证 |
| 用量统计 | `asdk_app_6ac33f40ad208191a08fbcfe6894796d` | OAuth 已完成；原生事件源及 5 个事件 schema 已发现；7 个工具未加载，实际只读调用待验收；钉钉与用量两项订阅未创建 |

CRM、邮件的事件参数 schema 均为空对象。两项自动化仅使用事件 trigger，没有另设独立 schedule；自动化默认时区为 `Asia/Shanghai`，每日事件的报告边界继续由事件源的 `Asia/Taipei` 规则控制。

### 用量统计图标与网页编辑

用户指定采用 Token Monitor 原始蓝底白色 Σ 图标，来源为 `/vol2/1000/Docker/token-monitor/app/assets/icon.png`（1024 × 1024）。资产已在 `ump45nose/usage-monitor-mcp` 提交并推送：`0ff2cef851ef58937ac29538fba280a5a48b2ce7`；保留原生 App ID，未改变服务或 OAuth。

| 资产 | 规格 | SHA-256 |
|---|---|---|
| `assets/plugin/token-monitor-original.png` | 1024 × 1024，707,382 字节 | `2c4a2e0bc9ad588ffa2efc64777a612f3fc879c6b6f9d9360ccae48d3d141edd` |
| `assets/plugin/token-monitor-web.png` | 256 × 256，7,606 字节，满足网页 10 KB 限制 | `76acfd21ec0d64cb7e602d2cef5b33d2d920946798c7923a1b825230e77dfff1` |

来源与尚未应用到网页的状态记录在 `assets/plugin/icon-source.json`。固定提交中的[网页上传图标](https://github.com/ump45nose/usage-monitor-mcp/blob/0ff2cef851ef58937ac29538fba280a5a48b2ce7/assets/plugin/token-monitor-web.png)已就绪。

原生 App 设置当前只提供名称、描述和刷新工具，没有独立图标编辑入口。尝试从网页下载现有包时遇到浏览器原生凭据保护；重新连接标签页的尝试被自动审批拒绝。本轮没有成功上传图标或修改网页图标，也没有通过其他路径绕过保护。浏览器恢复需要用户处理当前凭据状态或完成相应授权；资产准备完成不能记为网页图标已应用。

## 0.1.5 客户端兼容修复与生产验证

原生刷新之后发现 MCP 2 的 `server/discover`、`tools/list` 成功结果缺少必填缓存字段。公共运行时 0.1.5 补齐 `ttlMs: 0`、`cacheScope: "private"`，并在既有审计开关下仅记录 `method`、`protocol`、`status`、`event_count` 四项有限诊断字段。`status` 是 HTTP 响应开始时的状态，SSE 的 200 不能单独证明客户端成功解析。

运行时提交 `3084004d1011687f1b029003dcd073c078735b68`、新标签 `v0.1.5` 已推送。公共 wheel SHA-256 为 `74b5f1399f4dd79c438edca5632ac5bce1e5706b58e1e9935eb4e5aca84c8be7`；19 项针对性测试、Ruff、差异检查及离线锁检查通过。业务依赖已固定到该完整提交，业务实现未改变：

| 组件 | 固定依赖提交 | 生产状态 |
|---|---|---|
| CRM 0.1.3 | `505643d76ce4511d17dfcd766f057cf171c7e9b2` | 实际运行时 0.1.5；14:39:33（UTC+8）验收完成 |
| 邮件适配 0.1.2 | `647253ed9cad410ace5299a999c370c82c66f151`；子树 `14eb0527560299ce9fd5d1bc5ede7a375ca12279` | 实际运行时 0.1.5；14:39:51（UTC+8）验收完成 |
| 用量统计 0.1.0 | `bc83dd3bdd183b09586125940d9104ff91e7f3b7` | 实际运行时 0.1.5；14:40:09（UTC+8）验收完成；钉钉仍为 0.1.1 |

三个容器均实际加载公共运行时 0.1.5；依赖一致性及导入检查通过，健康请求返回 200，匿名 initialize 返回 401。原 env 内容、运行环境摘要，以及卷、端口、网络、运行用户和命令的完整签名保持一致。

| 组件 | 本次业务 wheel SHA-256 | 最终镜像 ID |
|---|---|---|
| CRM | `f8f818fd372311a1cfa06ed0f08065dc7010d39c6d3767b7dd14c07e1ed3bdeb` | `sha256:294f93393dfd3121dfbe7833983838b546dcf1af56f8ea53675a7903fe67ea9c` |
| 邮件 | `199ef9cb32853a28637ce554a405c62c9a234e8ebac33649c592e6909825a774` | `sha256:b397e71ba8508dfe97613bcc291bc01bb4e617033b3ff3bf3ece0770bab08828` |
| 用量统计 | `c46e9028bb8713b17e1acf0300736ba0a87914adaccd527c4202afd9c3560c57` | `sha256:169b0c852a856d979eacc37e83d7a19b3f3380df09e6c58f9088d88f798c119a` |

CRM、邮件 wheel 从各自固定提交导出源码后离线构建，METADATA 均要求 `mcp-platform==0.1.5`。用量 wheel 来源为干净提交 `a0373131e81cbb73edaedc90753c0d2fcc27afb5`，最终提交另记录构建摘要；新旧 wheel 的 9 个业务 Python 文件逐字节一致。

0.1.5 独立发布目录为 `/vol2/1000/Docker/stacks/mcp-platform/runtime/_mcp-events/releases/20261005-runtime-0.1.5`，主 `journal.json` 及三个 `switch/<crm|email|usage>/journal.json` 均为 `complete`。各服务的 `protocol-probe.json` 记录健康 200／匿名 initialize 401；`logs/<service>-runtime-version.log` 与 `logs/<service>-pip-check.log` 记录实际版本及依赖检查。该目录 `post-deploy-readonly.json` 是订阅创建前 14:42–14:43 的旧计数；服务端最近一次计数见上节 14:45:30 的只读复核，之后的 OAuth 和工具加载进展单独记录。下节 0.1.4 为已完成的前一轮部署记录。

## 0.1.4 已完成部署与版本

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

## 首轮业务与兼容性验证

以下为 0.1.4 首轮部署及业务实现的验证记录；0.1.5 增量验证见上节。

公共协议与只读挂载 24 项测试通过；CRM 15 项、邮件 28 项、钉钉 9 项针对性测试通过；统计 11 项日期与数据边界检查通过。覆盖原 MCP 协议兼容、认证与主体隔离、签名、订阅保存、重试、报告分页和去重、邮件超长头隔离及账号公平轮转。

生产实际验证：原 CRM 查询当日摘要、邮件账号发现成功；四个邮箱消费游标完成基线，无历史邮件发布；统计 API 与两个文件来源可读；钉钉待办和审批状态均 ready。所有生产 MCP 匿名请求返回 401，公网 TLS 保持验证。没有创建测试回调或发送测试事件。

## 维护与回退

0.1.5 使用上述独立发布目录及三个服务的切换记录；旧 0.1.4 发布证据完整保留。恢复仅比较并恢复本次镜像／Compose，必须先核对记录中的摘要，发生外部变更时停止覆盖。业务数据、事件订阅及 OAuth 状态不恢复旧快照。

CRM／邮件 0.1.4 首次事件部署仅更换业务镜像并合并事件环境变量，原卷、网络、命令、运行用户及认证字段保持一致。私有发布目录是 `/vol2/1000/Docker/stacks/mcp-platform/runtime/_mcp-events/releases/20261005-events-0.1.4`，各 `switch/<crm|email>/journal.json` 记录完整事务。需要回退本次 overlay 时使用同目录上级的 `switch_overlay.py --release <发布目录> rollback <crm|email>`；保留当前业务数据与 OAuth，不恢复旧数据快照。

统计使用 `usage-data` 持久卷、三个只读绑定目录及独立私有秘密文件。清单为 `deployment_mode: existing`：业务仓库准备固定 wheel／基础镜像的离线构建和 Compose；公共 mcpctl 协调认证、Tunnel 和 DNS。首次独立 OAuth 客户端使用公共 prepare_auth_change 显式传入私有 env 后创建；既有客户端后续由 mcpctl 正常协调。首次未提供 env 的入口尝试在任何共享配置改变前停止，回退记录 complete；之后独立客户端与公开入口均成功。

统计私有 bootstrap 记录、构建记录及入口事务位于 `/vol2/1000/Docker/stacks/mcp-platform/runtime/usage-monitor-mcp`。源仓为私有 `ump45nose/usage-monitor-mcp`。原 CRM、邮件 App ID 沿用既有原生连接；不用 Plugin Creator 重新包装。
