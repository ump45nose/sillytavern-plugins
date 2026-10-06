# 统一源码管理

唯一维护仓库为私有的 `https://github.com/ump45nose/personal-data-hub`。在 NAS 的 `/home/yuwk/code/personal-data-hub` 或 Mac 的 `/Users/yuwk/WorkSpace/Code/github/personal-data-hub` 修改、提交和发布源码。

| 原项目 | 当前维护位置 | 旧入口处理 |
| --- | --- | --- |
| Personal CRM | `apps/crm`；停用业务在 `legacy/crm-business` | NAS / Mac 旧项目目录移除，微信解释器直接使用本仓库 |
| usage-monitor-mcp | `apps/usage-monitor` | NAS 旧项目目录移除，独立 MCP 身份和数据保留 |
| Plaud | `collectors/plaud`、`agents/nas/plaud-sync.py`；原完整项目在 `legacy/plaud` | NAS 旧项目目录移除，下载和已有作业使用本仓库路径 |
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

执行 `python3 checks/source-management-smoke.py --deployed-nas` 验证维护位置、旧入口及私有运行文件边界；执行 `python3 checks/publication-audit.py` 检查 Git 当前索引和所有引用历史中的凭据候选及不应提交的文件。

源码回退使用统一仓库的历史提交或私有文件快照；已删除的旧项目入口无需恢复。私有运行文件、凭据和归档不需要回滚。不要删除备份里的 Python 环境或 Plaud 配置，当前运行入口仍使用它们。服务版本回退依照 [部署说明](deployment.md)。
