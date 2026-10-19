# 一次性任务的结果交付

标准输出一条 JSON，历史保存 `runs/<run-id>/result.json`，最新结果保存 `results/<platform>/<account>/latest.json`；Rewards 按 mode 分目录。结果不包含 Cookie、邮箱、模型凭据、网页、截图或完整接口响应。

| 字段 | 含义 |
|---|---|
| schema_version | 当前为 1；新增字段是可选扩展，旧核心结果仍可读取 |
| run_id / platform / account | 执行身份，account 是账号代号 |
| business_date | 调用方时区的业务日期，不能将昨日记录当今日成功 |
| started_at / finished_at / duration_ms | 启动器 UTC 起止时间与单调时钟耗时 |
| execution_status / reason | 执行情况与原因，不等同于业务全部完成 |
| business | 每项 complete / incomplete / unknown / not_applicable / blocked |
| details.metrics | 最多 32 项，每项固定包含 unit、current、max、before、after、delta |
| details.items | 最多 100 项，包含 id、name、status、reason，可选无查询参数的 HTTPS url |

数值无法确认时为 **null**；空 items 不代表清单已确认为空。unit 可为 points、coins、beans、days、count。余额 delta 只表示本次调用前后的余额差，不是全天获得积分；已有签到读回可产生 delta=0。任务名中的奖励额度不能代替到账金额。整体结果最多 64 KiB。

current 表示本次调用最近可核实的值；before/after 分别是执行前后观测。结束时读回失败会保留此前 current/max，但 after、delta 为 null；汇总应说明“结束读回未确认”，不能把执行前的进度冒充本次获得积分。

例如签到读回的 details：

```json
{
  "metrics": {
    "reward": {"unit":"points","current":4,"max":null,"before":null,"after":null,"delta":null},
    "streak": {"unit":"days","current":6,"max":null,"before":null,"after":null,"delta":null}
  },
  "items": []
}
```

平台从自己的页面/API 中提取事实，公共库只验证有界结构：

- Rewards：daily、desktop_search、edge_search、app_daily 进度；balance 前后值与差；explore 和 more_promotions 的可读资格进度；锁定数量、任务名称与未确认原因。连续打卡补充 bing_streak、daily_set_streak、app_streak 的当日计数及对应 `_days` 连续天数。桌面 App 周任务补充 `desktop_app_weekly` 周积分、`desktop_app_weekly_tasks` 总任务数及 `desktop_app_available` 当前已开放活动数；该能力完成不代表整周 70 分已全部获得。`platform_task_cycle` 明细标明平台当前任务日期，不能用 business_date 替代它判断任务重置。移动搜索仅当前清单可读时提供。后续失败可保留已确认阶段事实。
- Epic：当前促销、本次新领、已在库、未确认数量和每个商品的 ID、名称、商店链接、结论。清单失败时数量为 null；完整空清单才为 0。尚未处理的商品也属于未确认。
- Laowang：reward、streak、total_days 从签到页读取，汇总无需另读状态文件。
- Aliyun：balance 前后值与差、pending_points，各社区分别报告签到和奖励状态。
- V2EX：可解析时提供连续天数；上游没有明确的奖励数值契约时 reward 为 null，不重新解释旧余额列。
- SMZDM：签到、奖励、额外奖励独立报告；没有可信数值时 metrics 为空。

退出 0 表示执行正常、请求的业务完成或不适用；3 表示执行正常但仍有未完成、未知或受限项。1、75、124 表示执行失败、锁忙、总时限耗尽。超时可保留部分业务事实。

Hermes 生产封装保存实际调度尝试，包括锁忙和启动失败，避免旧 latest 成功遮住新失败。日报只读当日对应结果，不访问平台或补发签到；封装与通知路由维护在仓库外。
