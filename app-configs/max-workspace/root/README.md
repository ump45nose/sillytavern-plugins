# Max 多仓工作区

`max` 是父仓库，各工程通过 Git submodule 保持独立历史。父仓库记录工程的远端地址和当前提交版本。

开发导航见 [AGENTS.md](./AGENTS.md)，外部项目的附加说明按其中的规则读取。

## 工程

| 目录 | 工程 |
| --- | --- |
| `aide-detective` | AIDE Detective |
| `beluga` | Beluga |
| `magic-code-server` | Magic Code Server |
| `magic-link` | Magic Link |
| `magic-workspace` | Magic Workspace，包含自身的 submodule |
| `mermaid` | Mermaid |
| `official-toolkit` | Official Toolkit |
| `orca` | Orca |
| `sandking` | Sandking |

远端地址见 [.gitmodules](./.gitmodules)。

## 新克隆

为父仓配置并推送远端后，可以克隆整个工作区：

```sh
git clone <max-父仓地址>
cd <max-父仓目录>
git submodule update --init
```

已有父仓克隆可以初始化子仓：

```sh
git submodule update --init
```

需要初始化 `magic-workspace` 内部的子仓时，在该工程内执行：

```sh
git -C magic-workspace submodule update --init --recursive
```

`beluga` 当前提交含有 `.worktrees/remove-parent-code` Git 链接，但没有对应的 `.gitmodules` 配置。在该工程修正之前，从 `max` 执行全量 `--recursive` 操作会在 `beluga` 处失败。

## 日常开发

### 跨仓任务

Codex 中选择 **Worktree** 和 **Max 跨仓开发** 环境。新 worktree 会从各原仓当前 HEAD 创建独立子仓工作副本和任务分支；原目录的未提交修改留在原处。首次初始化只处理 9 个顶层子仓。

只涉及部分工程时，在 Max 主目录创建任务：

```sh
python3 scripts/max-git.py start fix-workspace orca magic-link
cd .worktrees/fix-workspace
```

打开输出的任务目录继续开发，在该目录内执行：

```sh
python3 scripts/max-git.py status
python3 scripts/max-git.py diff
python3 scripts/max-git.py commit -m "fix: workspace lifecycle"
python3 scripts/max-git.py merge
python3 scripts/max-git.py clean
```

- `setup <子仓...>`：向当前 Codex worktree 加入子仓。重复执行会复用已有工作副本。
- `status`：按仓查看 worktree、分支、任务提交数和工作区状态；从主目录执行也会列出运行中的任务。
- `diff`：展示任务启动以来的已提交、已暂存、未暂存和新增文件差异。
- `commit`：在各子仓任务分支提交，使用同一提交说明；可追加子仓名限制范围。
- `merge`：先检查所选原仓，再快进合并到启动任务时的开发分支。原仓有未提交修改、分支切换或提交分歧时，整理后再执行。
- `clean`：确认任务已合并且工作区干净后移除工作副本，保留任务分支。脚本创建的父仓 worktree 一并移除；Codex 创建的父仓由 Codex 管理。

Codex 的操作栏提供跨仓状态、差异、提交、合并和清理。配置在 [environment.toml](./.codex/environments/environment.toml)，脚本仅使用本地 Git，不调用模型。

Codex 清理钩子使用 `cleanup`：仅移除干净的子仓工作副本，始终保留子仓任务分支。清理前先提交；不要用原生 Handoff 搬运跨仓任务。任务记录保存在父仓 Git 公共目录的 `max-tasks/`，不会进入源码提交。

父仓原生 Git 面板仍显示 submodule 状态，文件级跨仓差异通过脚本查看。脚本不更新父仓 gitlink，也不推送远端；合并后如需固定版本，再按下面的方式更新父仓。

修改管理脚本后，在最后阶段运行 `PYTHONDONTWRITEBYTECODE=1 python3 tests/test_max_git.py`。

### 工程版本

进入对应工程，按该工程自己的规则修改、提交和推送。需要更新父仓记录的工程版本时，在 `max` 目录执行：

```sh
git add <工程目录>
git commit -m "chore: update submodule revision"
```

查看父仓及子仓状态：

```sh
git status
git submodule status
git submodule foreach 'git status --short'
```

## 现有目录

本次登记采用各工程当前的 HEAD，保留原有分支、未提交文件和 `.git` 位置。部分工程的 `.git` 还供其他 worktree 使用，因此保留现有布局。

父仓提交不会包含子仓的未提交修改。`git status` 中子仓显示 `modified content` 或 `untracked content` 时，进入该子仓查看详情。

`*-upstream-2026-10-10` 是现有工程的 worktree，保留在本地，不作为额外 submodule。

根目录现有的资料文件，以及 `aide-cli-prototype/`、`aide-interface-docs/`，尚未纳入父仓提交。
