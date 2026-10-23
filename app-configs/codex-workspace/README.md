# Codex 聚合开发配置

保存 `/home/yuwk/code` 聚合开发仓库在 2026-10-13 的配置。各项目源码通过 Git subtree 管理，统一 diff 和 worktree，项目提交仍拆分回各自原仓库。

NAS 的 Rust 构建缓存与产物放在 SSD，安装配置及现有 Codex 工程的迁移记录见 [Rust 构建存储](RUST-BUILD.md)。

## 配置内容

| 文件 | 用途 |
| --- | --- |
| `root/AGENTS.md` | 项目地图与 LLM 开发约定。 |
| `root/README.md` | 聚合仓库使用、项目同步、独立源码 checkout 和旧 Git 维护说明。 |
| `root/.gitignore` | 聚合范围外仓库、依赖、缓存及私有运行文件的忽略规则。 |
| `root/projects.json` | 12 个项目的目录、原远端和默认分支。 |
| `root/scripts/project.py` | 项目来源登记、拉取、拆分、推送及独立源码导出工具。 |
| `root/docs/import-2026-10-13.md` | 首次原位聚合的来源与迁移记录。 |
| `integration.patch` | 跨项目相对源码链接、MCP 锁定提交检出和用量 wheel 检查的必要适配。 |
| `snapshot.json` | 配置来源提交、文件清单与 SHA256。 |

Git 历史、原仓库索引与 worktree 元数据保留在 NAS 本机公共 Git 目录。各项目源码、私有环境、OAuth 状态、模型、数据库、图库和依赖由原来的 Git 与运行备份分别管理。

## 恢复与使用

1. 按项目原远端准备源码，使用完整历史的 Git subtree 建立聚合仓库；原位迁移保留旧 `.git` 和既有 worktree，步骤见 `root/README.md`。
2. 将 `root/` 中的配置复制到聚合根目录，保留各项目源码、依赖和仓库外运行数据。
3. 对尚未包含这些适配的源码，在聚合根应用 `integration.patch`；已包含适配的源码沿用现状。
4. 在聚合根执行 `python3 scripts/project.py remotes` 登记项目来源，新任务从聚合 `main` 创建 worktree。

`face-baseline` 和 `hermes-authoring` 当前没有 GitHub 远端，依赖本机保存的源码及原 Git。迁到其他主机时按实际来源更新 `projects.json`。秘密与正式部署入口继续在仓库外维护。

更新本配置时，从当前聚合根同步对应文件并更新 `snapshot.json`，然后只拆分和推送 `app-configs` 项目。

## 规则分发与迁移时机

此处保存的是 fn 聚合仓库的环境快照。分发通用规则时，保留项目地图、subtree/worktree 约束、正式部署入口和数据边界；不将本快照整份覆盖到其他环境。

主工作区按后续开发任务需要再迁移。迁移某项目时，检查已提交与未提交修改、原项目来源、旧 Git 归档和联调依赖；普通 clone 不包含本机 `project-origins` 和已有 worktree 元数据。
