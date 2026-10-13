# 远程服务器入口登记

本目录维护已有网关的公网接入清单与插件展示资料。业务仍在 `/vol2/1000/Docker/stacks/local-env-mcp` 的 systemd 网关和独立执行器中运行，Mac 源项目在 `/Users/yuwk/WorkSpace/Code/Github/local-env-mcp`。不复制业务代码或 OAuth 状态。

网关已经使用共享 Tunnel，本轮登记后验证原入口，保留 `https://local-env-home.172906573.xyz/mcp`、Authelia 客户端与 `28443` 端点、现有执行器、常驻会话以及业务 OAuth 状态；网页身份以当前原生连接为准。

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan local-env-mcp --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy local-env-mcp --target nas
```

existing 模式协调 Tunnel、DDNS、DNS 和清单中的认证配置。刷新期限由 `refresh_token_lifetime_days` 指定，默认 180 天；网关通过 `refresh-policy.patch` 从 `OAUTH_REFRESH_TOKEN_LIFETIME_DAYS` 读取同一期限，env 路径与重载命令登记在仓库外 NAS 目标中。期限没有变化时跳过重启；变更时仅重启网关，保留独立执行器和常驻会话。仅调整认证可运行 `mcpctl deploy local-env-mcp --target nas --auth-only`。业务运行时整体接入公共库另行推进。

## GPT 网页接入

2026-10-05 已通过原生 MCP 表单注册并完成 OAuth：[打开远程工作台](https://chatgpt.com/plugins/plugin_asdk_app_6ac285ae6e108191aa1251b71a1af699)。实际 App ID 为 `asdk_app_6ac285ae6e108191aa1251b71a1af699`，网页采用用户选定的 C 图标和场景描述，可「在聊天中试用」。该应用直接连接 `https://local-env-home.172906573.xyz/mcp`，没有旧「远程服务器接入」App 包装依赖。清单和本地 `.app.json` 已同步真实身份。

旧展示包 `plugins_6abf7eb3dd8881918cbef05a975592fd` 的 `0.1.5` release 与 skill 仅作历史资料。后续网页部署禁止使用 Plugin Creator，保留当前原生 App 身份；不要用旧包装包进行网页接入。首次网页注册未重启网关或执行器；后续刷新期限更新仅重启网关，未执行生产远程命令。
