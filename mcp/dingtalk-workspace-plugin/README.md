# 钉钉

连接钉钉官方办公能力，以本人身份处理私聊与群消息、会话历史和搜索，维护文档与批注、钉盘和知识库、通讯录、日历、待办、日志、审批、在线表格与 AI 表，读取听记和个人考勤，并处理钉钉邮箱。当前日常清单保留 245 个工具；实际可用性取决于对应服务授权和当前账号权限。

## 示例场景

- 查看我今天的钉钉日程和待办。
- 整理本周钉钉工作日志，准备周报草稿。
- 查询这条钉钉审批的当前进度。

## 插件文件与维护

- `plugin.json`：便携插件清单；`extensions.com.openai.interface` 保存名称、场景描述、示例提示和图标。
- `.codex-plugin/plugin.json`：兼容现有 Codex 插件格式，与便携清单保持一致。
- `.app.json`：引用已注册的个人 App，不包含令牌或 OAuth 密钥；使用者仍需拥有该 App 的访问权并完成授权。
- `assets/plugin/`：实际图标文件与可核对的来源说明。

在支持 GitHub 插件导入的客户端，选择此仓库并以仓库根目录为插件目录。此插件包复用已有 App，不包含新的 MCP 后端，也不扩大其权限。

平台中已创建的 Dev App 可在“设置 → 插件 → 对应插件 → 管理应用”编辑名称和描述。该页面没有图标上传控件，图标通过引用同一个 App 的插件包发布。

## ChatGPT 插件包发布

将根目录的 `plugin.json`、`.codex-plugin/plugin.json`、`.app.json` 和 `assets/plugin/` 打成 ZIP，压缩包内放一个与清单 `name` 相同的插件目录，目录内保留这些相对路径。不要包含数据库、聊天记录、令牌或业务部署文件。

在 ChatGPT“插件 → 添加 → 上传插件压缩包”上传，进入详情页后安装，核对名称、场景描述、图标及应用的“已连接”状态。新插件沿用 `.app.json` 中的原 App。卸载使用同一个 App 的插件入口会同时断开底层应用连接；元数据更新应直接发布到现有插件 ID。若连接已断开，在详情中重新连接原账号并核对“已连接”，保留原应用。

图标验收需在安装后刷新详情页和已安装列表，不能仅根据上传预览判断生效。

2026-10-02 创建的云端插件：[钉钉](https://chatgpt.com/plugins/Plugin_6e7cd81e16288191be4471f450fd078a)。已通过 Plugin Creator 原 ID 更新到 1.1.3。更新优先读取当前源文件和 release ID，再提交新版 ZIP；也可以使用“更多操作 → 上传新版本”。

更新展示信息时同步两份清单并保持 `.app.json` 的 App ID；无需重新创建 App 或变更 OAuth 配置。官方格式参考：https://developers.openai.com/codex/plugins/build/

1.1.1 已将展示名缩短，保留全部场景描述、示例提示和原 App ID。平台保存了图标清单与资源，但安装后详情图标仍可能回退为默认图标，需以实际页面验收，不能将包上传成功视为图标已生效。

1.1.2 用仅含兼容清单的 ZIP 通过网页上传原 ID，刷新后仍显示默认图标；1.1.3 恢复两份同步清单，保留官方 PNG 和原 App 映射。两种格式均未解决安装后的图标回退。

## 文档评论现状

官方独立的[钉钉文档互动服务](https://aihub.dingtalk.com/#/mcp-market/detail?mcpId=9784&detailType=marketMcpDetail)（`doc-comment`）已通过现有 MCPHub 接入。2026-10-10 曾因 `CLI_ORG_NOT_AUTHORIZED` 移除；2026-10-15 组织开启 CLI 调用权限、用户重新授权后，列表、详情和回复接口均已实测成功。

`mcphub/doc-comment.json` 保存非秘密接入配置，通过 MCPHub 原生管理 API 管理 `dingtalk-doc-comment`。最初仅启用三个读取工具；按后续补齐 dws 场景的要求，接入阶段曾开放上游全部 14 个评论工具；2026-10-21 日常清单保留其中 10 个，具体开关以 `mcphub/daily-profile.json` 为准。仅对列表、详情和回复做过只读业务验证，没有执行评论写入。使用官方 Streamable HTTP OAuth 地址，回调沿用现有公网入口的 `/oauth/callback`；客户端与令牌仅保存在现有 `/opt/mcphub/data`。需要重新授权时，从 MCPHub 取得当前授权链接；已使用或失败的旧回调链接不能再次用来完成授权。原十个钉钉服务、北向 OAuth 和 App 身份保留。

读取时先分页取得评论列表和真实 `commentKey`，再按 `topicId` 与 `commentKey` 查询详情及直接回复。本次上游列表未返回 `topicId`：对文档 JSONML 中的划词批注，可用引用文字匹配 `comment.contentId` 作为候选话题 ID，并以详情查询返回 `found=true` 确认；它不是 `commentKey`。不能唯一匹配或详情未确认时，不推断回复已读完。列表 `hasMore=true` 时继续传 `nextToken`；回复 `complete=false` 时继续传 `nextPageToken` 为 `pageToken`，需要完整回复链时再展开子回复。

2026-10-15 验证：「aide 快速进入需求」返回 4 条未解决评论，4 条详情均包含正文、引用、作者 ID 和时间；逐条回复查询均为 `complete=true`、`stopReason=END`，没有回复。「接口语义确认」在当前账号下返回空评论列表且 `hasMore=false`。本次样本没有多页结果或多层回复，尚未实测这些场景。

## dws 与现有 MCP

官方 [dws 架构](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli/blob/main/docs/architecture.md)以 MCP 调用为主要业务执行路径；本机完整 Schema 用于逐产品核对，不将多个 CLI 组合命令当作多个独立 MCP 工具。2026-10-15 已完成 dws 登录及组织 CLI 检查，CLI 个人/群聊会话列表只读查询成功。dws 仅用于取得官方接入地址及核对行为，日常请求仍由现有 MCPHub 直接转发官方服务。

完整业务场景接入清单、授权状态和已知上游差异见 [MCP 能力清单](mcphub/README.md)。`mcphub/additional-servers.json` 保存 25 个新增服务的非秘密配置。原服务不替换；AI 表格已定向刷新并补回 4 个角色管理工具。新增工具的可用性仍受个人授权、组织角色和具体业务开通状态限制，不能以工具发现成功代替业务验收。

2026-10-15 全部 OAuth（含独立个人考勤端点）已完成，共 36 个服务连接，公网根入口发现 1046 个工具。个人消息搜索及读取、群历史、AI 找人、AI 表格补充能力、个人合同、文档操作权限检查，以及个人考勤记录、员工班次和考勤规则已完成只读实测。完全重复的考勤上游及建群工具副本已合并；角色不足、组织未开通及 PAT 授权上下文错误见能力清单。

dws 的本地 HTML/Markdown 转换、文件下载落盘、组合命令和 Stream 事件消费属于客户端运行能力，不通过新增同名远程工具重复包装。本次没有启动持续监听、自动发送或其他后台任务。

## 当前日常清单与私聊验收

2026-10-21 按用户确认保留钉钉邮箱，将公网目录精简为 245 个工具：日常 177 个，加邮箱全部 68 个。启用 18 个服务，停用其余 18 个；保留 OAuth、连接配置和业务数据。已接入的完整上游目录是历史接入资料，当前可用范围以 [日常工具清单](mcphub/daily-profile.md) 和对应 JSON 为准；新增上游工具需重新对照该清单，不自动扩充日常范围。

本人发送入口在 `dingtalk-chat`：`send_direct_message_as_user`、`send_personal_message`、`send_message_as_user`。`dingtalk-robot.search_bots` 只解析机器人收件人，不承担本人发送。不能从“名下没有机器人”推断本人私聊不可用。

本次实际用户插件为 [原生钉钉连接](https://chatgpt.com/plugins/plugin_asdk_app_6ac287394cdc819192509b34e64e6557)，其 App ID 为 `asdk_app_6ac287394cdc819192509b34e64e6557`。上述早期插件包与 `.app.json` 引用历史包装 App，不能用上传包装包替代刷新这个原生连接，也不新建身份。

工具目录更新后，在原生连接详情执行 Refresh，确认出现本人发送入口，然后新开会话测试。故障会话原先只有旧的 411 个工具，缺 chat/im；2026-10-21 用户刷新后确认新会话已能看到本人发送工具，目录同步按用户反馈验收通过。官方流程见 [连接与测试](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt/)。

用户明确确认测试消息后，已通过既有公网 MCP 调用 `send_personal_message` 向“小虾米”投递一次文本私聊，发送状态返回 `SUCCESS`；按消息 ID 回读确认发送类型为 `user`、发送人为当前账号，正文及消息/会话标识一致。本次本人文本私聊实测通过，没有通过客户端或本地 dws 发送；群消息、附件及其他消息类型未在本轮测试。

## NAS Tunnel 接入

公网 MCP 地址仍为 `https://mcphub-home.172906573.xyz/mcp`。`mcp.app.yaml` 使用公共基座 existing 模式：共享 Cloudflare Tunnel 直接转发至现有 MCPHub，不替换官方钉钉服务或北向 OAuth，不移动 `/opt/mcphub/data`，不重建账号授权。

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan dingtalk --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy dingtalk --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl rollback dingtalk --target nas
```

首次迁移保留 NPM 原配置作为回退路径；DDNS 不再管理该域名的 A/AAAA，其他域名不变。入口验收使用健康检查、未认证 401 与 OAuth 发现，不调用钉钉写工具。

GPT Web 展示资料已确定沿用名称「钉钉」及官网官方 PNG，2026-10-04 已核对现有图标与官网当前资源字节一致。`mcp.app.yaml` 已登记原展示资料、图标路径和 App 绑定；原描述、开场提示和版本保留。当前仅保存资料，尚未发布或重新连接插件。
