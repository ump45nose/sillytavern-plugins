# Max 开发指引

## 工作约定

- 禁止防御性编程，说人话，仅在最后阶段测试。
- 先确定负责该功能的仓库，再读它的 `README`、`AGENTS.md` / `CLAUDE.md` 和相关代码；以当前代码为准。
- 各工程独立修改和提交；任务要求更新工程版本时，再更新父仓的 submodule 提交指针。
- `magic-workspace` 内的同名子仓和 `*-upstream-*` worktree 是其他工作副本，动手前确认目标目录。

## 9 个项目

| 项目 | 职责 | 入口 |
| --- | --- | --- |
| `aide-detective` | 架构治理、排障与 BugBot | `AIDE-ARCHITECTURE.md`、`scripts/`、`bugbot/` |
| `beluga` | 页面与组件资产、迭代和构建发布 | `app/common/service/facade/`、`app/biz/service-impl/` |
| `magic-code-server` | Agent 执行、工具调用、恢复与 Keep/Undo | `src/orchestration/`、`src/core/`、`src/tools/` |
| `magic-link` | 通用工作区、会话、沙箱生命周期与通知 | `app/interfaces/`、`app/application/` |
| `magic-workspace` | 数据集、评测回放与调优 | `datasets/`、`eval/`；产品源码回对应仓修改 |
| `mermaid` | 平台业务接口、权限与下游服务衔接 | `app/common/service/facade/`、`app/biz/service-impl/` |
| `official-toolkit` | Guide、Skill、Prompt 和 CLI 工具包 | `agent-guide/src/`、`skills/src/`、`prompts/src/`、`cli/src/` |
| `orca` | AIDE 工作区业务、资产、Git/DB 同步与编排 | `app/api/`、`app/application/`、`app/domain/` |
| `sandking` | 沙箱内初始化、文件、Git 与 magic-cli | `cmd/sandking/`、`internal/app/server/`、`internal/domain/` |

## 跨仓 Git

- Codex 选择 Worktree 和“Max 跨仓开发”环境；需要指定子仓时，从主目录执行 `python3 scripts/max-git.py start <任务名> <子仓...>`。
- 在任务目录内开发；用脚本的 `status`、`diff` 查看跨仓变更，`commit -m "说明"` 按仓提交，`merge` 合并，`clean` 清理。
- 新任务使用原仓 HEAD；原目录的未提交改动留在原处。首次初始化不递归进入嵌套子仓。
- 清理前先提交；任务分支保留。跨仓任务用脚本收尾，不使用原生 Handoff 搬运子仓改动。详细用法见 `README.md`。

## 选择修改位置

- 工作区的业务规则改 `orca`；通用会话、沙箱生命周期与通知改 `magic-link`；沙箱内执行与文件操作改 `sandking`。
- Agent 执行与工具协议改 `magic-code-server`；通用开发规则改 `official-toolkit`；数据集与评价方法改 `magic-workspace`。
- 平台接口与权限先查 `mermaid`，资产业务再查实际负责的服务；跨仓问题先沿调用链定位。

## 工具发布（按需）

- Skill、Guide、Prompt 工具包内容发布：[official-toolkit Jenkins](https://ci.example.invalid/job/pipeline/job/eco-max-official-toolkit/)。
- 沙箱内 CLI、Sandking、MCS 与镜像更新：[sandbox-template Jenkins](https://ci.example.invalid/job/pipeline/job/eco-agentic-sandbox-template/)。
- 涉及发布、回滚或核验生效时，按需使用本机的 `$release-aide-tooling` Skill；普通开发继续按各仓约定执行。

## 外部项目（按需）

仅当任务涉及外部后端或前端时，读取 [EXTERNAL-PROJECTS.md](./EXTERNAL-PROJECTS.md) 中对应项目；默认不加载该文件。
