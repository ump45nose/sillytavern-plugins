# Personal Info

- `personal-records/`：统一 Webhook 收集端，当前支持 Health 与 AutoAccounting，提供 SQLite 持久化和 HTTP/MCP。
- `plaud-archive/`：Plaud 采集、三源转录、Markdown 与音频归档，提供 HTTP/MCP。

两个应用保持独立依赖、运行身份、数据与 GitHub 仓库；聚合 Git 通过根目录 `projects.json` 和 `scripts/project.py` 同步。运行数据和私有配置不放在本目录。

- `personal-crm/`：独立人物、交互、附件及微信采集，HTTP/MCP 直接读写。
- `personal-review/`：运行中的 Hermes 日报/周报业务，直接读取 CRM、Records、邮件和 Skysight；状态保留在既有运行目录。
- Skysight Sync 继续使用其独立仓库和 SFTP 归档；不再经 Hub。

旧 Hub 已退役；各应用之间没有通用数据镜像或统一读取服务。既有 Usage Monitor 适配位于 `app-configs/token-monitor/usage-monitor/`，运行保持独立。
