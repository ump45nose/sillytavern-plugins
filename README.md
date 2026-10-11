# Agent Skills

ump45nose 的个人技能，供 Codex 和 Claude Code 使用。

| Skill | 用途 |
| --- | --- |
| [figma-make](skills/figma-make/SKILL.md) | 优先用 Browser Relay 提交 Make 提示词，桌面应用后备，经 MCP 接回代码与资源；附实测接口 |
| [github-pr-contributor](skills/github-pr-contributor/SKILL.md) | 检索、准备、验证并提交 GitHub Pull Request |
| [mcp-member-contributor](skills/mcp-member-contributor/SKILL.md) | 筛选、准备并提交 MCP 官方社区贡献 |

将 `skills/` 下需要的技能目录复制或链接到 `~/.codex/skills/`（Codex）或 `~/.claude/skills/`（Claude Code），然后按技能名调用。各技能的运行环境见其 `SKILL.md`。

Figma 登录密码保存在本机 macOS 钥匙串；仓库仅保存账号配置和钥匙串引用。浏览器登录与 Figma MCP OAuth 分别验证。运行状态、工作区和凭据不随仓库上传。

第三方代码的许可证随对应文件保留。
