# Rewards 其他日常任务与探索必应验收

2026-09-29 17:38（Asia/Taipei）正式 worker 结果：success=true，pending=[]，coverage=eligible-tasks-complete-with-restrictions。

| 项目 | 最新核实结果 |
|---|---|
| 每日活动 | 3/3 |
| 电脑搜索 | 100/100 |
| 探索必应 | 40/40，4 个已解锁主题均 complete=true |
| 其他可做日常任务 | 160/160，actionable=0 |
| 目标设置 | Amazon.com $5 Gift Card；仅跟踪并手动兑换，刷新后目标仍选中 |
| 本轮余额变化 | 70,693 → 70,753，增加 60 分 |

两张关注入口卡片各完成 10 分；四项探索各完成 10 分。目标设置后卡片已从待做清单移除，但没有另行观察到它的 5 分入账，不把这部分计入新增积分。

500 分 Bing App 新用户活动仍由平台标为不适用；另外四个探索主题仍锁定，不计入当前可执行上限。Edge 浏览时长和视觉搜索不属于本轮完成范围。

## 原因及修复

1. ShellCrash 的微软组为 DIRECT，使 Rewards 和 Bing 的地区不一致。现仅三个域名定向走用户既有“🧭 廉价手动”组：`www.bing.com`、`rewards.bing.com`、`edgeservices.bing.com`。该组仍选圣何塞07，微软服务组仍为 DIRECT。持久规则和有效配置均已核验，运行时规则正确。已有连接只关闭了这三个域名的连接。
2. 两张卡片需要普通网页点击事件；仅上游 promotion 元数据 priority/notsupported 不能判定卡片不可做。
3. 探索任务修复为正常浏览器入口、按主题搜索、每次读回同一 offer 的完成状态。已完成后立即停止，每主题最多两条查询，不在手机/电脑阶段重复探测。包含八个已知主题，锁定主题跳过。新主题激活路径按可用按钮处理；本次真实验收覆盖四个已激活主题，未对锁定主题做解锁测试。
4. 设置目标有二级弹窗，必须选择手动兑换，再 Next。只切换外层开关不会持久生效。实现只选择手动模式，验证选中后继续，不启用自动兑换或下单。
5. 国际页面使用 Daily Set / Edge 标签，补齐快照与每日活动脚本的标签兼容。
6. 快照直接读取当前会话的最新搜索/探索计数；结果汇总不再用旧日志冒充实时状态。

## 调度、报告与交付

正式 worker 已接入新执行器；青龙每日全量命令保持 `run_task.py rewards`，本次使用 `--activities-only` 做有界执行及完整当前状态复核。其结果写入正常 JSONL，Hermes 用户读取验证成功：

> Microsoft Rewards：成功（每日活动 3/3；探索必应 40/40；可做日常任务 160/160）

未发送额外 Telegram 消息，继续由既有日报 cron 推送。

- 公开快照：[f3983e1](https://github.com/ump45nose/microsoft-rewards-snapshot/commit/f3983e1)
- 私有部署：[6cf48f1](https://github.com/ump45nose/qinglong-benefits-deployment-private/commit/6cf48f1)
- [上游反馈](https://github.com/TheNetsky/Microsoft-Rewards-Script/issues/618#issuecomment-5887598422)
- 网络事实已写入 shared-state `infra/rewards_browser_routing` 并读回。
- 代码/规则修复前备份分别在 `backups/rewards-extra-code-20260929` 和 root 私有的 `backups/rewards-extra-20260929`。

验证范围：基本语法和 diff 检查、真实卡片/搜索/目标交互、正式队列 worker、最新快照及 Hermes 读权限。未运行大量回归测试。账户后续任务、资格和网站结构仍以当次实时状态为准。
