# 统一源码管理

唯一维护仓库为私有的 `https://github.com/ump45nose/personal-data-hub`。在 NAS 的 `/home/yuwk/code/personal-data-hub` 或 Mac 的 `/Users/yuwk/WorkSpace/Code/github/personal-data-hub` 修改、提交和发布源码。

| 原项目 | 当前维护位置 | 旧入口处理 |
| --- | --- | --- |
| Personal CRM | `apps/crm`；停用业务在 `legacy/crm-business` | NAS / Mac 旧项目目录移除，微信解释器直接使用本仓库 |
| usage-monitor-mcp | `apps/usage-monitor` | NAS 旧项目目录移除，独立 MCP 身份和数据保留 |
| Plaud | `collectors/plaud` / `agents/nas/plaud-sync.py` 管理下载；`processors/plaud` / `agents/nas/plaud-process.py` 管理转录、日报和摘要；旧实验在 `legacy/plaud` | NAS 旧项目目录移除，原定时作业转发至正式处理入口，状态、缓存和凭据保留 |
| Hermes 报告 | `legacy/hermes-reports`；当前归档适配在 `src/personal_data_hub` | 保留 GitHub 原仓库，旧本机维护目录已不再使用 |
| NAS 个人信息脚本 | `legacy/personal-jobs` | 原 `nas-cron-jobs/hermes`、`model` 中相关文件指向本仓库 |
| ShellCrash | `agents/nas/shellcrash` | 原运维仓库子目录指向本仓库，保持单一采集器 |
| Personal Review | `legacy/personal-review`；当前公共采集逻辑在 `src/personal_data_hub` | 原 Docker 目录的源码、测试和部署文件指向本仓库；运行目录留在原处 |
| Health / 财务旧接收器 | `legacy/health-webhook`；当前接收器在 `src/personal_data_hub/server.py` | 原私有目录仅源码文件指向本仓库 |
| Mac 微信 / Skysight 同步 | `agents/mac`、`apps/crm` | 继续从本仓库安装执行副本，保留既有授权路径及 launchd 身份 |
| Mac 展示端 | `apps/mac-client` | 当前客户端和固定凭据助手保留 |
| AutoAccounting | `integrations/autoaccounting` | 管理官方协议、版本锁和可选扩展；使用官方 APK |

Google、邮件、Git、Memos、Mem0 仍使用既有官方或独立服务，薄适配层在本仓库维护。NAS 其他运维、福利、媒体、Favsync 和钉钉等独立业务不迁入个人信息系统。

## 本次迁移

2026-10-07 整理 NAS 37 个旧源码入口和 Mac 的旧 CRM 目录。运行路径改为直接使用本仓库后，移除 NAS 的旧 CRM、用量、Plaud 项目入口及 Mac 旧 CRM 目录。NAS 运维和私有运行目录中的关联文件继续使用兼容链接，其他业务及持久数据保留。原工作区文件和私有环境在仓库外保存。

原 CRM、用量 MCP、Hermes 报告的主分支历史此前已导入主仓库。删除旧远端前，另外获取 CRM 和用量仓库的所有分支，使用 `archive/personal-crm/*`、`archive/usage-monitor-mcp/*` 标签保留其原始提交。Plaud 和原 Personal Review 没有独立 Git 历史，按源码快照维护。新仓库推送核对后删除 CRM 和用量 GitHub 原仓库；按用户要求保留 `hermes-cron-reports`。

补齐 Plaud 官方 MCP 登录辅助代码、原凭据 ACL 检查以及健康、邮件读取脚本的现有更新。原 Review 的健康模块转到仓库内共用脚本。用量 MCP 的构建校验现在比较原项目树与当前子目录树，防止迁入后错误复用已经过期的 wheel。

本轮只整理管理入口，不注册、恢复或重设旧业务任务。统一采集服务、MCP 身份、数据库、附件、设备授权和 Mac 固定凭据助手继续使用原配置。

## 私有文件

NAS 私有环境、旧文件快照和迁移回执位于 `/vol1/1000/personal-data-hub/source-backups/20261007-consolidation`；Mac 位于 `~/Library/Application Support/PersonalDataHub/source-backups/20261007-consolidation`。迁移回执列出每个旧入口、当前源码位置、备份位置及清理状态。原独立 `.git` 在新仓库推送校验后移除，历史由统一 Git 管理；未提交源文件快照继续保留。

保留的 `.venv`、已有 wheel 和 Plaud 设备配置通过被 Git 忽略的链接访问仓库外文件。新克隆不会包含这些链接，应按部署说明创建私有运行环境。`legacy/plaud/config.example.yaml` 和 `daily-v3.example.yaml` 只提供占位配置。

生产 `.env`、Google / Plaud 凭据、数据库、音频、模型、运行状态和 Mac 签名资料均不上传。后续个人信息功能开发只提交到 Personal Data Hub。

## 检查与回退

使用项目 Python 3.12+ 执行 `checks/source-management-smoke.py --deployed-nas` 验证维护位置、旧入口及私有运行文件边界；执行 `checks/publication-audit.py` 检查 Git 当前索引和所有引用历史中的凭据候选及不应提交的文件。NAS 可使用 `.venv/bin/python`；Mac 可使用 `apps/crm/.venv/bin/python`，省略 `--deployed-nas`。

源码回退使用统一仓库的历史提交或私有文件快照；已删除的旧项目入口无需恢复。私有运行文件、凭据和归档不需要回滚。不要删除备份里的 Python 环境或 Plaud 配置，当前运行入口仍使用它们。服务版本回退依照 [部署说明](deployment.md)。

## 验收记录：2026-10-07

- 私有 GitHub 主分支已推送并核对；三个原始分支标签和 `v0.3.0` 一并推送。未发现凭据候选或被提交的私有运行文件。
- GitHub `personal-crm`、`usage-monitor-mcp` 已删除，API 返回 404；`hermes-cron-reports` 保留。NAS / Mac 旧 CRM、NAS 用量和 Plaud 项目目录及旧独立 `.git` 已移除。
- NAS 37 个管理入口检查通过，统一采集、Health 接收器及 ShellCrash 三个服务运行正常，来源状态仍为 16 项。CRM HTTPS 健康检查和用量容器私网健康检查为 HTTP 200，用量容器状态为 healthy。
- 用量 11 项测试通过；构建校验验证旧项目树及子目录树两种基准，并拒绝源码变化后复用旧 wheel。HTTP / MCP 有界列表检查通过。
- Plaud 使用原 runtime 账号执行离线冒烟，验证 1,225 秒覆盖、25 秒尾块、缓存与单次请求门禁；未调用网络或真实 ASR。旧健康模块通过仓库内读取桥接检查。
- Mac 源码更新、旧目录与 `.git` 清理完成；微信 Agent 运行，Skysight 最近退出码为 0。客户端读取 16 个来源、53,224 条记录，并通过附件哈希验证。固定凭据助手的二进制哈希保持不变。
- MCP Platform 的 CRM 和用量应用目录已改为本仓库及清单所在子目录，锁定源码提交 `2f556b63fc9640f5bf557ba8487fc67344f24a33`，目录更新提交为 `5435b66`。NAS 的既有 source_roots 已指向本仓库。
