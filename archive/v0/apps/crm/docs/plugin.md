# CRM 的 GPT 网页接入

2026-10-05 已通过 ChatGPT「创建自定义 MCP 服务器」表单注册并完成 OAuth：[打开 CRM](https://chatgpt.com/plugins/plugin_asdk_app_6ac28369423081918d34fa531d15a62d)。名称为「CRM」，使用选定 C 图标；网页详情、已安装列表、已连接账户及「在聊天中试用」已核对，工具刷新请求返回 200。

实际 App ID 为 `asdk_app_6ac28369423081918d34fa531d15a62d`，MCP 为 `https://crm-home.172906573.xyz/mcp`。`mcp.app.yaml` 与本地 `.app.json` 已同步该原生身份。沿用 Authelia issuer、原客户端、数据卷、OAuth 密钥／盐及注册身份。CRM 工具现在提供人物、多人交互和附件的读写。

## 使用

- 查找张三，读取最近一个月的交互。
- 记录我、张三和李四今天一起吃饭。
- 修改某次交互的正文，附上文件。

## 后续维护

网页部署禁止使用 Plugin Creator；直接使用网页原生 MCP 表单及其编辑流程，更新保留上面的实际原生身份。网页图标只接受 PNG，最多 10 KB；本次压缩上传副本为 256×256，保留原始 `assets/plugin/logo-c.png`。不能用上传包或源文件回读代替网页图标与账户验收。

`plugin.json`、`.codex-plugin/plugin.json` 和 `.app.json` 作为可选桌面／便携展示资料，不替代原生网页发布。旧包装插件 `Plugin_df394834724481919c995db086c56b42` 的 `1.1.2` release 仅为历史记录，不作为网页入口。

完整记录与后续注意点见 `/home/yuwk/mcp-platform/docs/gpt-web-rollout-2026-10-05.md` 和公共项目 `AGENTS.md`。
