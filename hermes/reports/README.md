# Hermes 确定性报告

报告代码统一维护在 `nas-cron-jobs/hermes/reports/`，不再从独立
`hermes-cron-reports` 仓库同步旧版本。现有可信入口通过相对路径加载这里的代码，
`deploy-hermes.py` 已包含此目录；本次仅整理 Git 源码，没有执行部署或更改调度。

- `favsync/`：现有 Favsync 每日报告，仅报告异常。
- `media-automation/`：MoviePilot、FilmWatchlist、Emby Theme、MediaArchive 和
  DiscRemux 的只读报告；没有更新时间的来源只表示当前状态。
- `benefits-automation/`：读取福利任务的投递 JSON，包含 Steam；跳过已明确禁用的任务。
- `common/`：报告分发和 Telegram notice sender。

数据库以只读方式访问；API 凭据留在受保护的运行环境中，不进入报告、源码或调度定义。
MoviePilot 私有接口地址从 `HERMES_CRON_CONFIG` 指定的配置读取，默认
`/home/yuwk/cron/env/hermes.local.json`；请求不跟随重定向。
notice bot 的身份来自 `CRON_LOCAL_CONFIG` 指定的私有配置（同一默认文件）的
`notice_bot_username`，缺失时拒绝发送。主题路由继续由 Hermes 的私有配置维护。

## 合并来源与验证范围

源仓库：https://github.com/ump45nose/hermes-cron-reports
源提交：`924c636d6c05d6200bd9e3c4b61bc5328c3bdf0d`。
目标比较基线：`372c3492d97e1af7c8dbc0d5c506bd1ffe1db716`。

源仓库 9 个 Python 文件均已存在于此目录，其中 6 个内容完全相同；
`benefits-automation/daily_report.py`、`media-automation/daily_report.py` 和
`common/telegram_notice.py` 保留目标仓库已有的 Steam、禁用任务过滤、私有地址与
bot 身份配置改进，未用旧版覆盖。补齐目录说明、福利说明和忽略规则。
代码文件及可执行权限保持不变。

这是当前源码的对账收束，不是 Git 历史导入。原仓库仍保留原提交历史，本次未删除或归档。
没有运行真实报告、发送消息、读取生产数据库或验证 NAS 在线运行状态。
