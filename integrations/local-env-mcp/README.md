# 远程服务器入口登记

本目录仅维护已有网关的公网接入清单。业务仍在 `/vol2/1000/Docker/stacks/local-env-mcp` 的 systemd 网关和独立执行器中运行，Mac 源项目在 `/Users/yuwk/WorkSpace/Code/Github/local-env-mcp`。不复制业务代码或 OAuth 状态。

网关已经使用共享 Tunnel，本轮登记后验证原入口，保留 `https://local-env-home.172906573.xyz/mcp`、Authelia 客户端与 `28443` 端点、现有执行器、常驻会话以及 App／插件身份。

```bash
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl plan local-env-mcp --target nas
sudo -n /home/yuwk/mcp-platform/.venv/bin/mcpctl deploy local-env-mcp --target nas
```

existing 模式只更新 Tunnel、DDNS 和 DNS，不更新或重启 systemd 网关／执行器。当前阶段不做 GPT Web 插件发布。业务运行时接入公共库另行推进。
