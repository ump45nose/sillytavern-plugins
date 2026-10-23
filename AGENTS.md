# 聚合开发仓库

当前仓库统一管理下列项目源码和 worktree，通过 Git subtree 向各项目原仓库同步。

## 项目地图

| 目录 | 作用 |
| --- | --- |
| `personal-data-hub/` | 新版 Personal Hub：macOS 客户端与 hub-api 薄聚合后端；旧版封存在 `archive/personal-data-hub-v1-20261023` Git 标签。 |
| `personal-info/personal-records/` | 独立健康与账单 Webhook、SQLite 业务数据、HTTP / MCP。 |
| `personal-info/` | 独立 CRM、健康/账单、Plaud 与个人复盘；应用各自存储并提供接口，复盘直接读取各来源。 |
| `personal-info/plaud-archive/` | 独立 Plaud 采集、三源转录、Markdown 与音频归档及 HTTP/MCP CRUD。 |
| `nas-cron-jobs/` | NAS 定时任务、Hermes 调度包装、日报通知、巡检和容器启动；业务逻辑归业务项目。 |
| `mcp-platform/` | MCP 公共运行时、认证、应用登记和构建部署协调；业务工具归各自项目。 |
| `mcp/dingtalk-workspace-plugin/` | 钉钉插件资料、接入清单及事件代码，复用官方 MCP 和 MCPHub。 |
| `favsync/` | 收藏与媒体同步、片单和素材 API；`packages/downloads/` 提供独立下载能力。 |
| `media-automation/` | MoviePilot 插件、媒体搜索下载、Emby 主题及共享媒体能力。 |
| `benefits-automation/` | 签到、积分和免费游戏执行器；调度与通知归 `nas-cron-jobs/`。 |
| `sillytavern-workbench/` | SillyTavern Novel/RP 工作台、前端扩展、主题和设计稿。 |
| `face-baseline/` | 图库人脸质量评分、基线选择和网页管理。 |
| `app-configs/` | 可公开的软件配置与小型适配：Deskflow、Grok Bot、SubBoost、网页预览。 |
| `agent-skills/` | 自有 Codex/Claude 技能源码；安装位置独立维护。 |
| `hermes-authoring/` | Hermes profile 模板、共享状态工具和编排草案；运行 profile 在仓库外。 |

## 开发边界

- 聚合仓库只统一 Git 管理；各项目的业务、依赖与运行保持独立。
- 只在当前聚合 worktree 内修改受影响源码。
- 第三方贡献与模型参考仓库独立维护，不纳入聚合 Git。
