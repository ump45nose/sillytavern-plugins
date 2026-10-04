# 钉钉

连接钉钉办公数据，处理文档与知识库、组织通讯录、日历会议、个人待办、工作日志和周报、审批流程、在线表格与 AI 表，以及群聊和机器人消息。适用于“查我今天的日程和待办”“创建会议并邀请同事”“汇总或提交本周工作日志”“读取并更新钉钉表格”“查询审批进度”“整理项目文档”“向指定钉钉群发送通知”。支持文档创建与模板、日程查询和维护、待办及子任务、日志查询和提交、审批查询与处理、表格数据读写和 AI 表记录/视图/仪表盘管理。具体操作受当前账号和企业授权范围限制；没有提供考勤查询或打卡能力。

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

## NAS Tunnel 接入

公网 MCP 地址仍为 `https://mcphub-home.172906573.xyz/mcp`。`mcp.app.yaml` 使用公共基座 existing 模式：共享 Cloudflare Tunnel 直接转发至现有 MCPHub，不替换官方钉钉服务或北向 OAuth，不移动 `/opt/mcphub/data`，不重建账号授权。

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan dingtalk --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy dingtalk --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl rollback dingtalk --target nas
```

首次迁移保留 NPM 原配置作为回退路径；DDNS 不再管理该域名的 A/AAAA，其他域名不变。入口验收使用健康检查、未认证 401 与 OAuth 发现，不调用钉钉写工具。GPT Web App／插件发布是下一阶段，本轮不更新插件文件或身份。
