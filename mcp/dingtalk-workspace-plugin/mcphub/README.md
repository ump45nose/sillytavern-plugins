# 钉钉 MCP 能力接入

对照本机 dws v1.0.62 完整 Schema（31 个产品、1435 个 CLI 命令）、官方当前静态/补充端点与公开市场详情建立清单。1435 包括组合与本地命令，不能等同于 MCP 工具数。

## 已有覆盖

保留原文档、通讯录、日历、待办、日志、表格、AI 表、建群、审批、机器人和文档评论共 11 个上游。现有 `group` 只有建群能力，个人消息与完整群消息分别由新增 `im`、`chat` 服务提供。

## 新增上游

| MCPHub 名称 | 业务能力 | 官方市场 ID | 接入方式 |
| --- | --- | --- | --- |
| `dingtalk-agoal` | Agoal | [10283](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=10283&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-aisearch` | 企业人员与组织 AI 搜问 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-aitable-helper` | AI 表格补充接口 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-attendance` | 考勤打卡 | [9668](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9668&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-attendance-core` | 个人考勤记录、员工班次和考勤规则 | 官方 CLI 独立 attendance 端点 | 独立 OAuth |
| `dingtalk-chat` | 群聊会话、历史、搜索、Thread 与群成员 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-devdoc` | 开放平台文档 | [9352](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9352&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-ding` | DING | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-drive` | 钉盘 | [9638](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9638&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-hrbrain` | 组织大脑 | [10458](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=10458&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-hrmregister` | 智能人事 | [10042](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=10042&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-im` | 个人聊天、会话分组、消息、表情与收藏 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-live` | 直播 | [2406](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=2406&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-mail` | 邮箱 | [2721](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=2721&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-minutes` | AI 听记 | [9383](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9383&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-pat` | 行为授权 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-wiki` | 知识库 | [9730](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9730&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-whiteboard` | 钉钉白板 | [10592](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=10592&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-contract` | 智能合同 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-drive-internal` | 文档与知识库的操作权限检查 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-dingtalk-file` | 聊天表情图片上传 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-devapp` | 开放平台应用管理 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-deap-dev` | 数字员工开发 | 官方 CLI 登记 | 独立 OAuth |
| `dingtalk-mcpdev` | MCP 开发脚手架 | [10487](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=10487&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |
| `dingtalk-recruit` | 钉钉招聘 | [9642](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9642&detailType=marketMcpDetail) | 当前身份的 MCP 地址 |

## 配置与身份

`additional-servers.json` 的每项包含原生 `name`、`config`；有 `mcpId` 时先以已登录的同一组织和账号运行 `dws mcp url get <mcpId> -f json`，把返回的 `result.mcpURL` 私下填入有效配置。返回个人 key 地址时不附加模板的 OAuth 配置；返回 OAuth 地址时使用其 OAuth 配置。清单中的 `config.url` 是可公开的官方 OAuth 地址，不能将带个人 key 的实际地址写回源码。没有市场 ID 的项直接使用清单的标准 OAuth 配置。

通过现有 MCPHub 原生管理 API 添加缺失项，已存在的服务不重复创建；需要重新登录时使用 MCPHub 给出的当前授权链接。每个服务的授权客户端、刷新令牌与 PKCE 状态独立管理，不复制评论服务的令牌。原十个个人 key、北向 OAuth、App 身份、Tunnel 和数据目录继续沿用。

市场 ID 与 CLI 服务名不能仅凭名称互换。市场考勤 9668 实际对应 `attendance-wukong`，其 59 个工具与该端点完全相同；因此只保留市场接入。CLI 的独立 `attendance` 端点通过 `dingtalk-attendance-core` 补充，不能用市场 key 地址替代。新增 `chat.create_internal_org_group` 与原建群工具的描述、输入完全相同，源配置仅关闭新增副本，原建群能力继续提供。

普通服务 OAuth 与 PAT 行为授权分别核验。用户要求全部授权后，已使用当前登录身份对服务端声明的业务域批量申请永久行为授权；服务端复查返回 23 个业务域、236 项均为 `GRANTED`，`allGranted=true`，没有 selected 或 pending 项。这是当前 dws 身份的行为授权结果，不能代替 MCPHub 的独立 OAuth，也不代表获得招聘、人事等业务管理员角色。

全部业务域使用 `dws pat chmod --products <服务端声明的产品编码列表> --yes -f json` 申请；不能把 CLI 产品目录直接作为授权域目录。此次 `contract`、`dev`、`devapp`、`hrbrain`、`mcp`、`pat`、`recruit`、`whiteboard` 没有批量权限模板，服务端返回 `PAT_BATCH_PRODUCT_NOT_FOUND`；`docparse`、`oa-plus` 的 scope 则包含在所属业务域模板中，不能单独用作产品编码。未发现将多个独立 MCP 资源合并为一次 OAuth 的官方接入方式；继续使用各资源给出的授权地址，不扩造 scope 或复制其他资源的令牌。

维护使用现有 `/vol2/1000/Docker/stacks/mcp-platform/runtime/deployment.lock`。变更前记录目标配置及新增服务名，回退仅删除本次新增项或恢复本次工具开关，保留后续产生的令牌和客户端；不能还原整个旧状态文件。本次私有回退材料在 `/home/yuwk/.local/state/dingtalk-mcp-expansion-20261015/`。

## 当前验证与待办

2026-10-15：首轮 12 项 OAuth 及补充的 `dingtalk-attendance-core` OAuth 均已完成。原服务及新增服务共 36 个连接，没有待 OAuth 的服务；公网根入口实际发现 1046 个工具。源配置共 25 个新增项，已去除完全重复的考勤上游及建群工具副本。一次性授权链接不写入仓库。

已通过的新增服务只读样本：考勤个人设置、开发文档、钉盘文件列表、直播、邮箱账号、个人听记、知识库、个人白板模板和招聘身份查询。没有执行发消息、回复评论、审批、改考勤等写入操作。

首轮 OAuth 后通过现有根 MCP 入口实测：会话列表返回 10 个样本（5 个单聊、5 个群聊），单聊搜索及按真实消息 ID 读取成功，群历史分页返回消息且显式关闭已读处理；会话分组、AI 找人、AI 表格工作流列表、DING 机器人列表、个人合同查询和文档操作权限检查成功。按 userId 直接拉取的单聊样本返回成功空列表，非空单聊消息的验证来自搜索和按 ID 读取。上传服务只有写工具，本次没有上传图片。

个人考勤重新授权后，`dingtalk-attendance-core` 发现 5 个工具。通过公网 MCP 实测 `batch_get_employee_shifts`、`get_user_attendance_record`、`query_attendance_group_or_rules` 均返回 `success=true`；2026-10-15 当日样本的班次、打卡记录列表为空，规则查询返回 2 项。不据此推断用户当日没有打卡，也未修改考勤数据。

组织大脑返回 `4002`（无接口权限）；人事返回 `2001`（无花名册管理权限）；MCP 开发返回 `no_permission`（缺应用开发权限）；数字员工返回 `DIGITAL_EMPLOYEE_NOT_ENABLED`（组织未开通）。这些服务已连接并可发现工具，业务权限仍由组织管理员及业务系统控制。Agoal 与开发应用列表返回空对象 `{}`，业务结果未确认。

PAT 的原生 OAuth 调用返回 `PAT_INVALID_GRANT_CONTEXT`，服务端无法推导可信授权身份；单次按官方路由头对照结果相同，未改动运行配置。上文 dws 的 236 项授权结果保留，不能据此声称 MCPHub 中 PAT 批量工具已可用。

完整 CLI Schema 也有上游差异：`contact org invite-info` 在 CLI 实测返回 `TOOL_NOT_FOUND`。本机 1.0.62 的招聘旧列表/详情接口缺少当前账号的职位列表权限；当前官方源码 1.0.64 已移除旧招聘产品，市场 AI 诚聘使用 `query_recruiter_job_list`、`query_wh_job_detail` 等新工具，继续保留市场接入。考勤的上述 3 个接口由独立 `attendance-core` 接入，CLI 与公网 MCP 路径均已验证成功。

dws 的本地 HTML/Markdown 转换、落盘下载、批量组合与 Stream 事件消费保留为客户端运行能力，远程工具返回的数据与下载地址可由客户端继续处理。本次没有新增常驻 dws 转接层、自动监听或后台发送。

## 官方依据

- [静态服务目录](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/dc63092/internal/syncdata/endpoints.go)
- [补充服务](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/dc63092/pkg/edition/default.go)
- [显式直连端点](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/dc63092/internal/app/direct_runtime.go)
- [PAT 批量授权实现](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/dc63092/internal/pat/chmod.go)
- [旧招聘产品下线记录](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/dc63092/.changes/released/1.0.64/retire-recruit-product.md)
- [架构](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/main/docs/architecture.md)

本次目录读取仅用公开市场搜索/详情及官方源码；业务通过官方 MCP 或官方 CLI 调用，不使用网页私有业务接口。
