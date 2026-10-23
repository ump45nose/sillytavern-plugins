# Max 跨仓开发配置

保存 Max 的 submodule 工作区配置和跨仓任务脚本。各工程保持独立 Git 历史；同一个任务可涉及多个工程，由脚本按仓提交、合并和清理。

## 配置内容

- `root/.gitmodules`：9 个子仓的目录登记，远端地址已替换为示例地址。
- `root/.codex/environments/environment.toml`：Codex worktree 初始化、清理及操作入口。
- `root/scripts/max-git.py`：跨仓任务管理。
- `root/tests/test_max_git.py`：用临时仓库验证任务隔离和收尾。
- `root/README.md`、`root/AGENTS.md`、`root/.gitignore`：使用说明、项目约束和忽略规则。
- `snapshot.json`：来源提交和文件 SHA256。

## 恢复与使用

1. 准备父仓和实际子仓地址，将 `root/` 文件复制到目标工作区；替换 `.gitmodules` 及发布链接中的 `example.invalid`。
2. 初始化顶层子仓，按根 README 的要求处理嵌套子仓，避免直接对所有工程递归初始化。
3. 在 Codex 选择 Worktree 和“Max 跨仓开发”，或运行 `python3 scripts/max-git.py start <任务名> <子仓...>`。
4. 在任务目录用 `status`、`diff`、`commit`、`merge`、`clean` 完成跨仓任务。父仓版本指针按需另行更新。

此归档包含配置和通用 Git 工具，不包含子仓源码、子仓固定版本指针、凭据、运行数据和已有 worktree。复制这些文件不会自动迁移主工作区。

## 规则分发

个人级通用规则与项目级环境约束分别维护。更新四端通用规则时，保留各端独有的路径、运行入口、构建部署要求及本项目的 submodule/worktree 约束。归档中的 AGENTS.md 是原环境快照，不应整份覆盖到其他环境。
