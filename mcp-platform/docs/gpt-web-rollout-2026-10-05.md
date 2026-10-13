# GPT 网页端 MCP 接入结果（2026-10-05）

四个服务已通过 Browser Relay 在 ChatGPT 的「创建自定义 MCP 服务器」表单注册并完成 OAuth 连接。名称、完整描述、定稿图标、网页「在聊天中试用」和已连接账户已核对。远程工作台直接连接自己的 MCP 地址，没有旧「远程服务器接入」包装依赖；Media Download 不再仅限桌面端。

| 服务 | 正式网页入口 | MCP 地址 | 图标 |
|---|---|---|---|
| CRM | [打开](https://chatgpt.com/plugins/plugin_asdk_app_6ac28369423081918d34fa531d15a62d) | `https://crm-home.172906573.xyz/mcp` | C 方案 |
| 远程工作台 | [打开](https://chatgpt.com/plugins/plugin_asdk_app_6ac285ae6e108191aa1251b71a1af699) | `https://local-env-home.172906573.xyz/mcp` | C 方案 |
| 钉钉 | [打开](https://chatgpt.com/plugins/plugin_asdk_app_6ac287394cdc819192509b34e64e6557) | `https://mcphub-home.172906573.xyz/mcp` | 钉钉官方 |
| Media Download | [打开](https://chatgpt.com/plugins/plugin_asdk_app_6ac288ae39908191a239ef999f71fa54) | `https://media-download-home.172906573.xyz/mcp` | MoviePilot 官方 |

这些是当前用户的私有开发模式连接；未向公开目录提交。旧 Plugin Creator 展示包保留为历史记录，其 ID/release 不再作为本次网页部署身份；业务清单与本地 `.app.json` 已同步实际原生 App ID。旧包仍可能出现在「由你创建」目录，使用上表的原生入口。

## 图标与浏览器

网页表单只接受 PNG，文件上限 10 KB。四个正式设计分别生成 256×256 上传副本，实际大小均约 4–6 KB，原始图标保留。上传文件与摘要见 `gpt-web-plugin-drafts/2026-10-04/web-icons/index.json`。截图证据留在仓库外 `/home/yuwk/.codex/artifacts/gpt-web-2026-10-05/`。

公网 Browser Relay 可直接使用已登录浏览器；无需恢复旧远程服务器 App 或安装另一套远程环境。设备 capability 保存在仓库外，不放入文档、日志、插件或 URL。中继重连后 tab ID 会变化，应重新列举；使用独立任务标签页与 session，避免操作其他任务的页面。

## Media Download CIMD 修正

host 网络网关最初没有出站代理，获取 ChatGPT `client.json` 时连接被重置，网页报告 `Client Not Registered`。在原网关私有 env 中复用 NAS 现有 7890 HTTP/HTTPS 代理，`NO_PROXY` 排除回环和 Authelia，并保留原 SNI 兼容、TLS、CIMD 签名和 PKCE 校验。只重新创建网关容器，镜像、下载后端、业务数据、密钥、加密盐和 OAuth 状态未替换。重试原 OAuth 请求后连接成功，没有重复创建 App。

变更使用共享部署锁和私有记录，失败按文件摘要比较后回退。当前成功记录：`/vol2/1000/Docker/stacks/mcp-platform/runtime/media-download-mcp/releases/20261004T171916-outbound-proxy/journal.json`。健康 200；携带正确 Host 的未认证 MCP initialize POST 返回 401。无状态入口 GET 可返回 405，不能用 GET 判断认证行为。

本次只核对网页连接、图标和必要协议冒烟，没有执行生产写入或真实下载。后续更新保持这里记录的原生 App 身份；网页部署禁止使用 Plugin Creator，不用 ZIP 包保存结果代替真实网页接入。
