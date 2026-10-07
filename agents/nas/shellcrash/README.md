# ShellCrash traffic accounting

This collector samples Mihomo's authenticated `/connections` API once per
second and stores hourly aggregates in SQLite.

It exists because the installed Zashboard connection history is browser-side
IndexedDB. Zashboard is excellent for interactive inspection, but it only keeps
history while a dashboard client is receiving closed-connection events. This
collector provides host-side 24x7 accounting independent of any open browser.

## Runtime data

- SQLite fact store: `/var/lib/shellcrash-traffic/traffic.sqlite3`
- Static HTML report: `/var/lib/shellcrash-traffic/report.html`
- AI snapshot: `/var/lib/shellcrash-traffic/ai-summary.json`

The AI JSON is a rolling 30-day snapshot refreshed hourly. It includes totals,
daily traffic, top policy groups, pools, subscription sources, exit nodes,
hosts, processes, source IPs, rules, collector metadata, and collection gaps.

No controller secret, request body, request path, or subscription URL is stored
in the traffic database or AI JSON.

## Commands

月报入口由本仓库的 `shellcrash-traffic-report` 符号链接维护，指向同目录
`shellcrash_traffic.py`。NAS 的 `/home/yuwk/cron/scripts/shellcrash-traffic-report`
应直接链接到该入口。脚本按启动文件名选择月报模式；不要将月报入口包装为
`python3 shellcrash_traffic.py`，否则会进入采集模式并拒绝 `--html`。

```bash
/home/yuwk/cron/scripts/shellcrash-traffic-report --month 2026-10 --group host --top 50
/home/yuwk/cron/scripts/shellcrash-traffic-ai-export --days 30 --top 100
```

The separate SubBoost refresh timer fetches the local private subscription,
validates it with the running Mihomo core, and replaces the active ShellCrash
configuration only when the validated content changed.

## 月报入口修复验收：2026-10-07

NAS 兼容入口已直接链接到本仓库的月报入口，恢复按启动文件名选择报告模式。
临时 SQLite 数据验证 HTML 生成、兼容链接和采集模式通过。原
`shellcrash-traffic-report.service` 于 16:30（UTC+8）执行成功，退出码为 0，
更新 17,075 字节的当月 HTML；原定时器保持 active，实时采集进程及其入口未变，
最新采样持续更新。回退信息保存在仓库外
`/vol1/1000/personal-data-hub/source-backups/20261007-shellcrash-report-entry`。
