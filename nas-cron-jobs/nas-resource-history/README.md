# NAS resource history

Install this job alone with `bash nas-resource-history/install.sh`.

The existing sysstat collector records CPU, paging, memory, disks and network
every minute. Its package configuration retains seven days and compresses
older files after three days. The package cron helper skips collection when
systemd is running, so this does not create a second sampler.

The minute timer also saves the largest processes by RSS plus swap, CPU and
physical I/O, blocked processes/threads, their wait channels and cgroup
ownership, dirty memory and pressure.
It uses two procfs snapshots one second apart. Process command lines,
environment variables and application payloads are never collected.

Source stays here; deployment is `/home/yuwk/cron/scripts/nas-resource-history.py`
and `/home/yuwk/cron/systemd/nas-resource-history.*`. Runtime records are in
`/var/log/nas-resource-history/snapshots.jsonl`, with seven daily rotations.
Journald preserves logs across boots, capped at 256 MiB and seven days while
keeping at least 2 GiB free. Existing rsyslog logs and rotation remain active.

This records evidence only. It does not kill processes, restart business
services, change resource limits on existing workloads, or send notifications.
