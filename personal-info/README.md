# Personal Info

- `personal-records/`：统一 Webhook 收集端，当前支持 Health 与 AutoAccounting，提供 SQLite 持久化和 HTTP/MCP。
- `plaud-archive/`：Plaud 采集、三源转录、Markdown 与音频归档，提供 HTTP/MCP。

两个应用保持独立依赖、运行身份、数据与 GitHub 仓库；聚合 Git 通过根目录 `projects.json` 和 `scripts/project.py` 同步。运行数据和私有配置不放在本目录。
