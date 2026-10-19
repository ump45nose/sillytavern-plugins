#!/usr/bin/env python3
"""Save host pressure and process resource use without command lines or secrets."""
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def processes():
    result = {}
    for directory in Path('/proc').glob('[0-9]*'):
        try:
            status = dict(line.split(':', 1) for line in (directory / 'status').read_text().splitlines())
            stat = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            counters = dict(line.split(':', 1) for line in (directory / 'io').read_text().splitlines())
            cgroup = (directory / 'cgroup').read_text().strip().split(':', 2)[2]
        except (FileNotFoundError, ProcessLookupError):
            continue  # Processes can exit between these procfs reads.
        result[int(directory.name)] = {
            'pid': int(directory.name), 'name': status['Name'].strip(),
            'state': stat[0], 'threads': int(stat[17]), 'cgroup': cgroup,
            'rss_kib': int(status.get('VmRSS', '0 kB').split()[0]),
            'swap_kib': int(status.get('VmSwap', '0 kB').split()[0]),
            'start_ticks': int(stat[19]), 'cpu_ticks': int(stat[11]) + int(stat[12]),
            'read_bytes': int(counters['read_bytes']), 'write_bytes': int(counters['write_bytes']),
        }
    return result


def main():
    before = processes()
    started = time.monotonic()
    time.sleep(1)
    after = processes()
    elapsed = time.monotonic() - started
    tick_rate = os.sysconf('SC_CLK_TCK')
    for pid, row in after.items():
        previous = before.get(pid)
        if previous is not None and previous['start_ticks'] == row['start_ticks']:
            row['cpu_percent'] = round((row['cpu_ticks'] - previous['cpu_ticks']) / tick_rate / elapsed * 100, 1)
            row['read_bytes_per_second'] = round((row['read_bytes'] - previous['read_bytes']) / elapsed)
            row['write_bytes_per_second'] = round((row['write_bytes'] - previous['write_bytes']) / elapsed)
        else:
            row['cpu_percent'] = row['read_bytes_per_second'] = row['write_bytes_per_second'] = None
        del row['start_ticks'], row['cpu_ticks']
    rows = list(after.values())
    blocked_threads = []
    for path in Path('/proc').glob('[0-9]*/task/[0-9]*/stat'):
        try:
            stat = path.read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'D':
                pid = int(path.parts[2])
                owner = after.get(pid)
                blocked_threads.append({'pid': pid, 'tid': int(path.parts[4]),
                                        'cgroup': owner['cgroup'] if owner else None,
                                        'wait_channel': (path.parent / 'wchan').read_text().strip()})
        except (FileNotFoundError, ProcessLookupError):
            continue
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    record = {
        'time': datetime.now().astimezone().isoformat(),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'loadavg': Path('/proc/loadavg').read_text().strip(),
        'memory_kib': {key: int(memory[key].split()[0]) for key in
                       ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree', 'Dirty', 'Writeback', 'Slab', 'SReclaimable')},
        'pressure': {kind: Path('/proc/pressure', kind).read_text().strip() for kind in ('cpu', 'io', 'memory')},
        'process_count': len(rows),
        'blocked_process_count': sum(row['state'] == 'D' for row in rows),
        'blocked_thread_count': len(blocked_threads),
        'blocked_threads_by_cgroup': dict(Counter(row['cgroup'] for row in blocked_threads)),
        'blocked_threads': blocked_threads[:30],
        'top_memory': sorted(rows, key=lambda row: row['rss_kib'] + row['swap_kib'], reverse=True)[:12],
        'top_cpu': sorted((row for row in rows if row['cpu_percent'] is not None),
                          key=lambda row: row['cpu_percent'], reverse=True)[:12],
        'top_io': sorted((row for row in rows if row['read_bytes_per_second'] is not None),
                         key=lambda row: row['read_bytes_per_second'] + row['write_bytes_per_second'], reverse=True)[:12],
        'blocked': [row for row in rows if row['state'] == 'D'][:30],
    }
    with Path('/var/log/nas-resource-history/snapshots.jsonl').open('a') as output:
        output.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
