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

```bash
shellcrash-traffic-report --month 2026-10 --group host --top 50
/home/yuwk/cron/scripts/shellcrash-traffic-ai-export --days 30 --top 100
```

The separate SubBoost refresh timer fetches the local private subscription,
validates it with the running Mihomo core, and replaces the active ShellCrash
configuration only when the validated content changed.
