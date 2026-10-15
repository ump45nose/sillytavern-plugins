"""未来消息的持久媒体队列；文件晚到或上传失败不改变正文水位。"""

from __future__ import annotations

import fcntl
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .checkpoint import save
from .config import as_datetime


class MediaQueue:
    def __init__(self, config):
        self.config = config
        self.path = Path(
            config.media_queue_path or str(Path(config.checkpoint_path).with_suffix(".media.json"))
        ).expanduser()
        self.spool = self.path.with_suffix(".files")

    @contextmanager
    def state(self):
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            lock_path = Path(lock.name)
            lock_path.chmod(0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.path.exists():
                state = json.loads(self.path.read_text())
                if not isinstance(state.get("jobs"), dict) or not as_datetime(
                    state.get("enabled_since")
                ):
                    raise ValueError("media_queue_invalid")
            else:
                state = {"enabled_since": datetime.now(UTC).isoformat(), "jobs": {}}
            yield state
            save(str(self.path), state)

    def initialize(self):
        with self.state():
            pass

    def enqueue(self, interactions):
        with self.state() as state:
            since = as_datetime(state["enabled_since"])
            for item in interactions:
                message = item.get("message")
                if not message or int(message["record"].get("msg_type") or 0) not in {
                    3,
                    34,
                    43,
                    49,
                }:
                    continue
                if as_datetime(item["occurred_at"]) < since:
                    continue
                key = item.get("source_message_key") or item["source_event_key"]
                state["jobs"].setdefault(
                    key,
                    {
                        "event_key": item["source_event_key"],
                        "message_key": item.get("source_message_key"),
                        "message": message,
                        "state": "pending",
                        "attempts": 0,
                        "next_retry": 0,
                    },
                )

    def update(self, key, result=None, complete=False, status="pending"):
        with self.state() as state:
            job = state["jobs"].get(key)
            if job is None:
                return
            if complete:
                del state["jobs"][key]
                return
            if result:
                job["file"] = result
            job["state"] = status
            job["attempts"] += 1
            job["next_retry"] = time.time() + min(3600, 60 * 2 ** min(job["attempts"] - 1, 6))

    def run_once(self, client, resolver=None):
        from .media_reader import LocalMediaResolver, MediaUnavailable

        counts = Counter()
        with self.state() as state:
            ready = [
                (key, dict(job))
                for key, job in state["jobs"].items()
                if job["next_retry"] <= time.time()
            ][:8]
        if not ready:
            with self.state() as state:
                return {"pending": len(state["jobs"])}
        self.spool.mkdir(parents=True, exist_ok=True, mode=0o700)
        resolver = resolver or LocalMediaResolver(self.config, self.spool)
        try:
            for key, job in ready:
                try:
                    file = job.get("file")
                    if not file or not (self.spool / file["id"]).is_file():
                        file = resolver.resolve(job["message"])
                        if file is None:
                            self.update(key, complete=True)
                            counts["not_media"] += 1
                            continue
                        # 已取得的原文件先落入耐久队列，微信缓存轮转不影响重试。
                        self.update(key, result=file, status="ready")
                    params = {"name": file["name"]}
                    if job["message_key"]:
                        params["message_key"] = job["message_key"]
                    with (self.spool / file["id"]).open("rb") as source:
                        response = client.put(
                            self.config.webhook_url.rstrip("/") + "/media/" + job["event_key"],
                            params=params,
                            content=iter(lambda: source.read(1024 * 1024), b""),
                            headers={
                                "X-Webhook-Token": self.config.webhook_token,
                                "X-Content-SHA256": file["id"],
                                "Content-Type": file["media_type"],
                            },
                        )
                    response.raise_for_status()
                    status = response.json().get("status")
                    if status not in {"attached", "deleted"}:
                        raise ValueError("media_receipt_invalid")
                    self.update(key, complete=True)
                    counts[status] += 1
                    with self.state() as state:
                        in_use = any(
                            j.get("file", {}).get("id") == file["id"]
                            for j in state["jobs"].values()
                        )
                    if not in_use:
                        (self.spool / file["id"]).unlink(missing_ok=True)
                except MediaUnavailable as error:
                    self.update(key, status=error.code)
                    counts["unavailable"] += 1
                except Exception:
                    self.update(key, status="retry")
                    counts["retry"] += 1
        finally:
            resolver.close()
        with self.state() as state:
            counts["pending"] = len(state["jobs"])
        return dict(counts)
