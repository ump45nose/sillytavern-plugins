"""Independent, bounded source workers with automatic failure backoff."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import update

from .contracts import canonical, utcnow
from .storage import runs


def retry_delay(failures, interval):
    return min(max(15, int(interval)), 30 * 2 ** min(max(0, failures - 1), 7))


def stop_worker(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def interrupted(store, source, reason):
    # Never close another live/manual worker's run.
    try:
        with store.lock("source:" + source), store.engine.begin() as c:
            c.execute(update(runs).where(runs.c.source == source, runs.c.status == "running").values(
                ended_at=utcnow(), status="failed", error=canonical({"type": "InterruptedError", "reason": reason})))
    except RuntimeError as exc:
        if str(exc) != "collector_busy":
            raise


@dataclass
class Worker:
    process: subprocess.Popen
    started: float
    timeout: int


def serve(store, config, config_path=None):
    selected = {s: v for s, v in config['sources'].items()
                if v.get('enabled', True) and v.get('collection_mode') != 'push'}
    active, deadlines, failures = {}, {}, {}
    limit = max(1, min(8, int(config.get('collector_workers', 3))))
    path = str(config_path or os.environ.get('HUB_CONFIG', '/home/yuwk/.config/personal-data-hub/config.json'))
    hub = str(Path(sys.executable).parent / 'hub')
    worker_command = [hub, '--config', path, '--skip-schema-init']
    previous_handler = signal.getsignal(signal.SIGTERM)
    processing_worker = None
    processing_deadline = 0
    processing_kind = None
    processing_next = 'drain'
    processing_backfill_pending = config.get('processing_backfill_on_start', False)
    processing_interval = int(config.get('processing_interval_seconds', 6 * 60 * 60))
    model_worker = None
    model_deadline = 0

    def shutdown(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    try:
        while True:
            now = time.monotonic()
            # 微信模型提炼暂缓，后续分析模块统一设计；当前不启动模型 Worker。
            # if model_worker is not None:
            #     code = model_worker.process.poll()
            #     if code is None and now - model_worker.started >= model_worker.timeout:
            #         stop_worker(model_worker.process); code = 1
            #     if code is not None:
            #         model_worker = None
            #         model_deadline = now + (30 if code else 5)
            # if model_worker is None and now >= model_deadline and not processing_backfill_pending and config.get('processing_enabled', True):
            #     from .processing.insights import budget_remaining
            #     from .processing.repository import ProcessingRepository
            #     if budget_remaining(store, config) > 0 and ProcessingRepository(store).has_pending(lane='model'):
            #         process = subprocess.Popen([hub, '--config', path, 'process-pending', '--lane', 'model', '--limit', '20'], start_new_session=True)
            #         model_worker = Worker(process, now, 900)
            #     else:
            #         model_deadline = now + 60
            # One separate, bounded lane; processing never consumes collector slots.
            if processing_worker is not None:
                code = processing_worker.process.poll()
                if code is None and now - processing_worker.started >= processing_worker.timeout:
                    stop_worker(processing_worker.process)
                    code = 1  # Durable leases recover unfinished work on the next drain.
                if code is not None:
                    if processing_kind == 'rebuild' and code == 0:
                        processing_backfill_pending = not store.cursor('processing:reading-backfill').get('complete', False)
                    processing_next = 'drain' if processing_kind == 'rebuild' else 'rebuild'
                    processing_worker = None
                    processing_deadline = now + processing_interval
            if config.get('processing_enabled', True) and processing_worker is None and now >= processing_deadline:
                from .processing.repository import ProcessingRepository
                command = None
                has_pending = ProcessingRepository(store).has_pending()
                if processing_backfill_pending and (processing_next == 'rebuild' or not has_pending):
                    command = worker_command + ['rebuild-content', '--limit', '50', '--background-page']
                    processing_kind = 'rebuild'
                elif has_pending:
                    command = worker_command + ['process-pending', '--limit', '1000', '--max-seconds', '300']
                    processing_kind = 'drain'
                if command:
                    process = subprocess.Popen(command, start_new_session=True)
                    processing_worker = Worker(process, now, 480 if processing_kind == 'drain' else 120)
                else:
                    processing_deadline = now + processing_interval
            for source, worker in list(active.items()):
                code = worker.process.poll()
                if code is None and now - worker.started < worker.timeout:
                    continue
                if code is None:
                    stop_worker(worker.process)
                    interrupted(store, source, '采集超过执行时限，已结束进程并安排自动重试')
                    code = 1
                del active[source]
                interval = int(selected[source].get('interval_seconds', 6 * 60 * 60))
                failures[source] = failures.get(source, 0) + 1 if code else 0
                delay = retry_delay(failures[source], interval) if code else interval
                deadlines[source] = now + delay
                print(canonical({'source': source, 'worker_exit': code, 'retry_in_seconds': delay if code else None}), flush=True)
            for source in sorted(selected, key=lambda s: deadlines.get(s, 0)):
                if len(active) >= limit:
                    break
                if source in active or now < deadlines.get(source, 0):
                    continue
                settings = selected[source]
                timeout = max(30, int(settings.get('run_timeout_seconds', 900)))
                process = subprocess.Popen(worker_command + ['collect', source], start_new_session=True)
                active[source] = Worker(process, now, timeout)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
        if processing_worker is not None:
            stop_worker(processing_worker.process)
        if model_worker is not None:
            stop_worker(model_worker.process)
        for source, worker in active.items():
            stop_worker(worker.process)
            interrupted(store, source, '采集服务停止时本轮中断，下次启动自动继续')
