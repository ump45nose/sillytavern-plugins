# Code · 聚合开发仓库

`/home/yuwk/code` 就是跨项目开发入口。各个自有项目通过 Git subtree 纳入普通子目录，统一查看 Git diff、提交和创建 worktree；项目提交仍可拆分回各自原 GitHub 仓库。

项目职责和 LLM 开发约定见 [AGENTS.md](AGENTS.md)，远端与默认分支见 [projects.json](projects.json)。`contrib-agents/`、`OFIQ-Project/`、`face-quality-reference/` 和 `token-monitor-upstream/` 保持独立，未纳入聚合 Git。

## Codex 开发

任务继续绑定当前 `/home/yuwk/code` 项目。新任务使用 Worktree，起点选择聚合 `main` 或任务分支。在任意纳入聚合的项目目录运行 Git，都属于当前聚合 worktree。

各项目按自身 README 安装依赖、构建和检查。新 worktree 只有已跟踪源码，不把主 checkout 的可写 `.venv`、`node_modules` 或私有运行目录链接进去。源码之间的相对链接在 worktree 内解析。

主 checkout 保留原有源码位置、依赖和运行文件；正式 Compose、cron、身份及持久数据沿用既有入口。切换主 checkout 分支或拉取源码可能影响已有构建与源码挂载，任务改动先在 worktree 完成，再按受影响服务的部署流程处理。

## 按项目同步

同步工具调用原生 Git/subtree，不自动提交、测试或部署。使用完整历史导入和拉取，保留 subtree 同步提交。

```bash
python3 scripts/project.py list

# 新克隆聚合仓库后登记项目远端；同一仓库的 worktree 共享远端配置
python3 scripts/project.py remotes

# 拉取原项目默认分支并合入当前聚合分支
python3 scripts/project.py pull favsync

# 将当前 HEAD 的项目提交拆成独立分支，供检查
python3 scripts/project.py split favsync --branch export/favsync

# 推送到原 GitHub 仓库的任务分支，目标分支必须显式指定
python3 scripts/project.py push favsync codex/update-favorites
```

跨项目修改可一起提交，然后分别推送：

```bash
git add favsync nas-cron-jobs
git commit -m "Update favorite synchronization and daily report"
python3 scripts/project.py push favsync codex/update-favorites
python3 scripts/project.py push nas-cron-jobs codex/update-favorites
```

在原项目分别创建 PR，合并后分别 `pull` 回聚合分支。`split` 和 `push` 只包含所选项目目录，根指引及其他项目不会进入该远端。拉取可用 `--branch` 指定原项目分支。

已有未提交源码和未忽略的新文件用独立聚合提交保留。首次推送某项目时，这些已有改动也会进入拆分结果，应一并审阅。初始来源见 [导入记录](docs/import-2026-10-13.md)。根配置快照维护在 [app-configs/codex-workspace](app-configs/codex-workspace/README.md)，通过 app-configs 原仓库独立同步；服务部署按各项目流程处理。

## 独立源码 checkout

需要以原项目目录结构执行发布审核或构建时，导出当前已提交的项目源码：

```bash
python3 scripts/project.py checkout personal-crm /absolute/source-export/personal-crm
```

这会创建独立 Git checkout，并将它的 `origin` 指向原项目远端；不复制依赖、密钥或运行数据，也不更改现有部署来源。按项目文档准备依赖和选择部署源码。MCP CLI 已有 `--source` 参数可显式选取导出的业务目录；私有 NAS target、服务和授权不在本次迁移中改写。

## 原 Git 与既有 worktree

原子仓库的 `.git` 移入根公共 Git 目录的 `project-origins/<项目名>.git`，保留对象、分支、标签、索引、远端和配置。已有三个独立 worktree 的 Git 引用已更新，它们继续属于原项目 Git，源码路径不变。新任务统一使用聚合 worktree。

在主 checkout 可查看旧项目历史：

```bash
git --git-dir=.git/project-origins/favsync.git log --oneline -10
```

`face-baseline` 和 `hermes-authoring` 暂无 GitHub 远端，同步工具以各自归档 Git 作为本机来源，可推送新任务分支。这些归档和迁移状态属于本机 Git 元数据，不随普通 clone 分发；将这两个项目配置为远程仓库后，更新 `projects.json` 并重新登记远端。

项目目录内不再保留独立 `.git` 标记。原 Git 归档只供查看历史、维护既有独立 worktree 及接收本机项目分支，当前源码以聚合提交为准。
