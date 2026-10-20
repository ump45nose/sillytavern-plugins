"""Bundled, metadata-only Mac proxy accounting with durable acknowledged upload."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import threading
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

SUPPORT = Path.home() / "Library/Application Support/PersonalDataHub/Network"
CONFIG = SUPPORT / "config.json"
STATUS_LOCK = threading.Lock()
STOP = threading.Event()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("w") as f:
            os.chmod(temporary, 0o600)
            f.write(encoded(value)); f.flush(); os.fsync(f.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def status(**fields):
    with STATUS_LOCK:
        path = SUPPORT / "status.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        save(path, {**old, **fields, "checked_at": now()})


def load_core():
    bundled = Path(__file__).with_name("shellcrash_traffic.py")
    path = bundled if bundled.exists() else Path(__file__).resolve().parents[2] / "nas/shellcrash/shellcrash_traffic.py"
    spec = importlib.util.spec_from_file_location("proxy_accounting", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def load_config():
    value = json.loads(CONFIG.read_text())
    if not re.fullmatch(r"[a-f0-9]{32}", value.get("device_id", "")):
        raise ValueError("network_device_identity_invalid")
    return value


def proxy_config(config):
    path = Path(config.get("proxy_config") or Path.home() / "Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml")
    text = path.read_text()
    def field(key):
        match = re.search(r"(?m)^" + re.escape(key) + r":\s*([^\r\n]*)", text)
        return match.group(1).strip().strip("\"'") if match else ""
    unix = field("external-controller-unix")
    if unix:
        return "unix", unix, ""
    host = field("external-controller")
    if not host.startswith(("127.0.0.1:", "localhost:", "[::1]:")):
        raise ValueError("local_proxy_controller_unavailable")
    return "tcp", host, field("secret")


def connections(config):
    transport, address, secret = proxy_config(config)
    if transport == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(3)
        try: sock.connect(address)
        except BaseException: sock.close(); raise
        client = http.client.HTTPConnection("localhost", timeout=3); client.sock = sock
    else:
        client = http.client.HTTPConnection(address, timeout=3)
    try:
        headers = {"Accept": "application/json"}
        if secret: headers["Authorization"] = "Bearer " + secret
        client.request("GET", "/connections", headers=headers)
        response = client.getresponse()
        if response.status != 200: raise OSError("proxy_controller_http_error")
        payload = json.loads(response.read(32 * 1024 * 1024 + 1))
        rows = payload.get("connections")
        if not isinstance(rows, list): raise ValueError("connections_schema_invalid")
        # Inner connections are the core's own checks, not proxied applications.
        return [r for r in rows if isinstance(r, dict) and (r.get("metadata") or {}).get("type") != "Inner"]
    finally:
        client.close()


class Accounting:
    def __init__(self, path, config):
        self.core = load_core(); self.config = config
        self.db = self.core.open_db(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS upload_outbox (external_id TEXT PRIMARY KEY, kind TEXT NOT NULL, raw TEXT NOT NULL, content_hash TEXT NOT NULL)")
        self.previous = {}; self.initial = True; self.last_tick = None; self.gap = None
        prior = self.db.execute("SELECT value FROM collector_meta WHERE key='last_sample'").fetchone()
        if prior:
            self.start_gap(prior[0], "collector not running"); self.end_gap(now())

    def queue(self, eid, kind, raw):
        value = encoded(raw)
        self.db.execute("INSERT INTO upload_outbox VALUES(?,?,?,?) ON CONFLICT(external_id) DO UPDATE SET kind=excluded.kind,raw=excluded.raw,content_hash=excluded.content_hash", (eid, kind, value, digest(raw)))

    def start_gap(self, started, reason):
        if self.gap is None:
            self.gap = self.db.execute("INSERT INTO collector_gaps(started_at,reason) VALUES(?,?)", (started, reason)).lastrowid
            self.queue_gap(); self.db.commit()

    def queue_gap(self):
        row = self.db.execute("SELECT id,started_at,ended_at,reason FROM collector_gaps WHERE id=?", (self.gap,)).fetchone()
        self.queue("gap:" + str(row[0]), "collector_gaps", dict(zip(("id", "started_at", "ended_at", "reason"), row)))

    def end_gap(self, ended):
        if self.gap is not None:
            self.db.execute("UPDATE collector_gaps SET ended_at=? WHERE id=?", (ended, self.gap)); self.queue_gap(); self.db.commit(); self.gap = None

    def sample(self, rows, stamp=None):
        stamp = stamp or now()
        if self.last_tick is not None and (time.monotonic() - self.last_tick > 5 or
                (datetime.fromisoformat(stamp) - datetime.fromisoformat(self.last_sample)).total_seconds() > 5):
            self.start_gap(self.last_sample, "sample interrupted or system asleep")
            self.initial = True
        if self.gap is not None: self.end_gap(stamp); self.initial = True
        current = {}; pending = defaultdict(lambda: [0, 0])
        for row in rows:
            eid = str(row.get("id") or "")
            if not eid: continue
            up, down = max(0, int(row.get("upload") or 0)), max(0, int(row.get("download") or 0))
            old_up, old_down = self.previous.get(eid, (0, 0)); current[eid] = (up, down)
            if self.initial: continue
            key = list(self.core.row_key(row)); key[0] = datetime.fromisoformat(stamp).astimezone(ZoneInfo(self.config["timezone"])).strftime("%Y-%m-%dT%H:00")
            value = pending[tuple(key)]; value[0] += up - old_up if up >= old_up else up; value[1] += down - old_down if down >= old_down else down
        self.previous = current; self.initial = False
        columns = ("bucket", "destination_ip", "host", "process", "source_ip", "category", "pool", "source_tag", "exit_node", "rule", "upload_bytes", "download_bytes")
        # Fact update and its pending upload commit together.
        with self.db:
            for key, counts in pending.items():
                if not any(counts): continue
                self.db.execute("INSERT INTO traffic_hourly VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET upload_bytes=upload_bytes+excluded.upload_bytes,download_bytes=download_bytes+excluded.download_bytes", (*key, *counts))
                row = self.db.execute("SELECT * FROM traffic_hourly WHERE " + " AND ".join(k + "=?" for k in columns[:10]), key).fetchone()
                self.queue("hour:" + digest(dict(zip(columns[:10], key))), "traffic_hourly", dict(zip(columns, row)))
            self.db.execute("INSERT INTO collector_meta VALUES('last_sample',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (stamp,))
            self.queue("meta:last_sample", "collector_meta", {"key": "last_sample", "value": stamp})
        self.last_sample = stamp; self.last_tick = time.monotonic()
        return {"active_connections": len(rows), "identified_applications": sum(bool((r.get("metadata") or {}).get("process")) for r in rows)}


def remote_tokens(tokens):
    return " ".join("'" + str(t).replace("'", "'\"'\"'") + "'" for t in tokens)


def upload_once(path, config, execute=subprocess.run):
    db = sqlite3.connect(path, timeout=10)
    try:
        rows = db.execute("SELECT external_id,kind,raw,content_hash FROM upload_outbox ORDER BY kind,external_id LIMIT 250").fetchall()
        if not rows: return 0
        records = [{"external_id": r[0], "kind": r[1], "raw": json.loads(r[2])} for r in rows]
        body = {"device_id": config["device_id"], "timezone": config["timezone"], "records": records}
        body["batch_id"] = digest(body)
        command = remote_tokens([config.get("hub_cli", "/home/yuwk/code/personal-data-hub/.venv/bin/hub"), "ingest-network"])
        result = execute(["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", config["host"], command], input=encoded(body).encode(), capture_output=True, timeout=45)
        if result.returncode: raise OSError("network_upload_failed")
        reply = json.loads(result.stdout)
        if reply.get("committed") is not True or reply.get("batch_id") != body["batch_id"] or reply.get("accepted") != len(rows):
            raise ValueError("network_upload_ack_invalid")
        with db:
            # A fact may have changed while the acknowledged version was in flight.
            db.executemany("DELETE FROM upload_outbox WHERE external_id=? AND content_hash=?", [(r[0], r[3]) for r in rows])
        return len(rows)
    finally: db.close()


def uploader(path, config):
    while not STOP.is_set():
        try:
            count = upload_once(path, config)
            if count: status(last_upload=now(), upload_error=None)
            with sqlite3.connect(path) as db: pending = db.execute("SELECT COUNT(*) FROM upload_outbox").fetchone()[0]
            status(pending_records=pending)
            if count == 250: continue
        except Exception as error: status(upload_error=type(error).__name__)
        STOP.wait(60)


def main():
    global SUPPORT, CONFIG
    parser = argparse.ArgumentParser(); parser.add_argument("--access-check", action="store_true"); parser.add_argument("--watch", action="store_true")
    parser.add_argument("--support", type=Path, default=SUPPORT); args = parser.parse_args()
    SUPPORT = args.support; CONFIG = SUPPORT / "config.json"; os.umask(0o077)
    config = load_config()
    if args.access_check:
        rows = connections(config)
        print(encoded({"readable": True, "active_connections": len(rows), "identified_applications": sum(bool((r.get("metadata") or {}).get("process")) for r in rows)})); return
    SUPPORT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (SUPPORT / ".collector.lock").open("a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError("network_collector_already_running")
        if not config.get("enabled"): return
        for signum in (signal.SIGTERM, signal.SIGINT): signal.signal(signum, lambda *_: STOP.set())
        path = SUPPORT / "traffic.sqlite3"; accounting = Accounting(path, config)
        worker = threading.Thread(target=uploader, args=(path, config), daemon=True); worker.start()
        status(enabled=True, scope="proxy", device_id=config["device_id"])
        try:
            while not STOP.is_set():
                started = time.monotonic()
                try:
                    result = accounting.sample(connections(config)); status(last_sample=accounting.last_sample, collection_error=None, **result)
                except Exception as error:
                    accounting.start_gap(now(), type(error).__name__); status(collection_error=type(error).__name__)
                STOP.wait(max(0.05, 1 - (time.monotonic() - started)))
        finally:
            accounting.db.close(); status(enabled=False)


if __name__ == "__main__":
    try: main()
    except Exception as error:
        print(encoded({"readable": False, "error": type(error).__name__})); raise SystemExit(1)
