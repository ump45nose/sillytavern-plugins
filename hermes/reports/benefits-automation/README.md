# 福利任务异常报告

读取现有福利任务投递 JSON，汇总失败、缺失或需要介入的结果，不调用福利 API。
任务包括既有来源与 Steam；Steam 只读合格候选会标为待授权领取。
私有 `benefits-deployment.json` 中 `enabled: false` 的任务不产生缺失／失败告警，
保留历史结果。配置不可读或过大仍明确报错。

入口为本目录 `cron_entrypoint.py`，可信调度入口仍由 `deploy-hermes.py` 管理。
路径、秘密与运行数据保持在现有 NAS 私有运行环境；本次未改变任何 schedule。
参见 [报告目录说明](../README.md)。
