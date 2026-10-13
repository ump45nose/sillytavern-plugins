# 聚合开发仓库

禁止防御性编程，说人话，只在最终阶段测试。

当前仓库统一管理下列项目源码和 worktree，通过 Git subtree 向各项目原仓库同步。

## 项目地图

| 目录 | 作用 |
| --- | --- |
| `personal-data-hub/` | 个人数据采集、归档、处理和只读 MCP；含 CRM、用量监控、Mac 客户端及 Plaud。 |
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

## 工作约定

- 先读受影响项目的 `AGENTS.md`、README 和当前实现。以现状与任务范围为准，只改受影响对象，保留已有改动。
- 一个任务使用一个聚合 worktree，在当前 worktree 内修改源码；跨项目源码引用使用相对路径。各项目独立安装依赖，不共享可写虚拟环境、`node_modules` 或运行数据。
- 复用既有模块、依赖锁和设施。没有任务依据就不加兼容层、兜底分支、重试、默认值或公共抽象。
- 源码、部署、数据分离。正式 NAS Compose 在 `/vol2/1000/Docker/stacks/<group>/compose.yaml`，cron 产物在 `/home/yuwk/cron/`；保留身份、密钥、授权、持久卷和媒体路径，私有文件不入库。
- 涉及部署、目录或权限，先读 `fn-service-ops`；网络故障读 `fn-network-diagnostics`；MCP 公共运行时、清单和生成器读 `mcp-platform-maintenance`，网页连接读 `mcp-web-connection`。按实际场景读取资料。
- 实现完成后只验证受影响路径，优先使用既有检查。说明实际变化、验证结果及未验证事项；运行脚本前确认它是否操作正式服务。
- 跨项目改动可一起提交；用 `scripts/project.py` 拉取、拆分和逐项目推送，操作见根 README。推送和部署分别处理，项目版本锁仍引用原项目提交。
- 旧 Git 元数据保存在根仓库公共 Git 目录的 `project-origins/` 下，已有独立 worktree 保留。普通项目目录统一使用聚合 Git；第三方贡献及模型参考仓库继续独立维护。
