# 钉钉公网入口与 GPT 网页连接

`mcp.app.yaml` 维护入口与正式展示资料。既有 MCPHub 1.0.38 继续从 `http://192.168.31.201:3100` 聚合钉钉官方 MCP，公网为 `https://mcphub-home.172906573.xyz/mcp`，保留北向 OAuth；未重启 MCPHub 或复制业务代码。

2026-10-05 已通过 ChatGPT「创建自定义 MCP 服务器」原生表单注册并完成现有 MCPHub 账号授权：[打开钉钉](https://chatgpt.com/plugins/plugin_asdk_app_6ac287394cdc819192509b34e64e6557)。实际 App ID 为 `asdk_app_6ac287394cdc819192509b34e64e6557`；官方图标已在网页详情与已安装列表确认。清单和本地 `.app.json` 已同步该原生身份。

旧 Plugin Creator 展示包 `Plugin_6e7cd81e16288191be4471f450fd078a` 的 `1.1.4` release 仅为历史记录。后续网页部署禁止使用 Plugin Creator，不用 ZIP 包保存结果代替原生连接。

NAS `source_roots.dingtalk` 指向本目录；旧业务工作目录已删除，不恢复旧目录。existing 模式协调入口和清单声明的北向 OAuth 期限。清单使用 `oauth_provider: mcphub`，刷新期限省略时为 180 天；NAS 目标引用现有设置文件。只有期限变化时短暂停止／启动 MCPHub，保留注册、令牌和所有官方后端，不调用钉钉写工具。官方图标源见 `assets/plugin/SOURCES.md`；网页压缩副本及 10 KB 限制见平台网页部署记录。

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan dingtalk --target nas
```
