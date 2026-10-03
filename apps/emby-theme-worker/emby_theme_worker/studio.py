"""Private Unix-socket control plane. No listener on TCP and no browser secrets."""
from __future__ import annotations
import dataclasses
import hashlib
import json
import os
import re
import shutil
import socketserver
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .audio import sha256
from .media_limits import MAX_AUDIO_BYTES, MAX_UPLOAD_BYTES, STREAM_CHUNK_BYTES
from .models import Candidate, MediaItem
from .publisher import ThemePublisher
from .security import contained

ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")

def public_source(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("only supported HTTPS public media links are accepted")
    host = (parts.hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "music.youtube.com", "youtu.be"}:
        identity = parts.path.strip("/") if host == "youtu.be" else parse_qs(parts.query).get("v", [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identity):
            raise ValueError("a single YouTube video is required")
        return f"https://www.youtube.com/watch?v={identity}", "youtube"
    if host in {"www.bilibili.com", "bilibili.com"} and re.fullmatch(r"/video/(BV[A-Za-z0-9]+|av[0-9]+)/?", parts.path):
        return "https://www.bilibili.com"+parts.path, "bilibili"
    if host == "music.163.com":
        identity = parse_qs(parts.query or parts.fragment.partition("?")[2]).get("id", [""])[0]
        if identity.isdigit():
            return "https://music.163.com/#/song?id="+identity, "netease"
    if host == "y.qq.com" and re.fullmatch(r"/n/ryqq/songDetail/[A-Za-z0-9]+", parts.path):
        return "https://y.qq.com"+parts.path, "qqmusic"
    raise ValueError("unsupported source; upload audio instead")

class Studio:
    def __init__(self, config, db):
        self.config, self.db = config, db
        self.root = Path(config.staging_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.candidates = {}
        self.mutex = threading.Lock()
        # Do not replay a destructive operation whose response was lost.
        with db.connect() as conn:
            conn.execute("UPDATE studio_jobs SET status='interrupted',error='worker_restarted' WHERE status='running'")

    def asset(self, identity: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("invalid asset id")
        path = self.root/identity
        if not contained(str(path), str(self.root)):
            raise ValueError("invalid asset path")
        return path

    def media(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT s.emby_id,s.payload,i.source_provider,i.status,i.score,i.output_sha256,c.locked,c.quality FROM library_snapshot s LEFT JOIN items i USING(emby_id) LEFT JOIN controls c USING(emby_id) WHERE s.present=1")
            output = []
            for row in rows:
                raw = json.loads(row["payload"])
                item=MediaItem(**{k:v for k,v in raw.items() if not k.startswith('_')})
                output.append({"id": row["emby_id"], "name": raw["name"], "original_title":item.original_title, "aliases":item.aliases, "year": raw["year"], "type": raw["item_type"], "source": row["source_provider"], "status": row["status"], "score": row["score"], "locked": bool(row["locked"]), "quality": row["quality"], "owned": bool(row['source_provider'] and row["output_sha256"]), "anime": item.is_anime, 'has_file':(item.directory/'theme.mp3').exists(), 'emby_visible':raw.get('_emby_visible')})
        return output

    def sync(self, worker):
        rows = list(worker.emby.iter_items())
        visible={item.id for item in worker.emby.iter_themed()}
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE library_snapshot SET present=0")
            for item in rows:
                conn.execute("INSERT INTO library_snapshot VALUES(?,?,1) ON CONFLICT(emby_id) DO UPDATE SET payload=excluded.payload,present=1", (item.id, json.dumps({**dataclasses.asdict(item),'_emby_visible':item.id in visible})))
        return {"items": len(rows)}

    def submit(self, kind: str, item_id: str | None, payload: dict) -> str:
        if kind not in {"sync", "search", "prepare", "extract", "trim", "apply", "register", "auto", "upgrade"}:
            raise ValueError("unknown task")
        if kind != "sync" and (not item_id or not ID.fullmatch(item_id)):
            raise ValueError("item id required")
        allowed = {"keyword", "candidate_id", "asset_id", "start", "end", "adopt", "expected_sha256", "basis"}
        payload = {k: v for k, v in payload.items() if k in allowed}
        if payload.get("keyword"):
            payload["keyword"] = str(payload["keyword"])[:200]
        return self.db.enqueue(kind, item_id, payload, priority=10 if kind in {"auto", "upgrade"} else 0)

    def candidate_from_url(self, item_id: str, url: str) -> str:
        source, transport = public_source(url)
        candidate_id = uuid.uuid4().hex
        self.candidates[candidate_id] = (item_id, Candidate("manual", "User source", source, transport=transport))
        return candidate_id

    def upload(self, item_id: str, content: bytes) -> str:
        if not ID.fullmatch(item_id) or not content or len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("invalid upload")
        identity = uuid.uuid4().hex
        directory = self.asset(identity)
        directory.mkdir(mode=0o700)
        (directory/"source").write_bytes(content)
        (directory/"meta.json").write_text(json.dumps({"item_id": item_id, "kind": "upload", "created": time.time()}))
        return identity

    def candidate(self, worker, item, identity):
        cached = self.candidates.get(identity)
        if cached:
            if cached[0] != item.id:raise ValueError('candidate belongs to another item')
            return cached[1]
        # Re-resolve an expired handle by its durable, non-secret source hash.
        # Never persist signed transport URLs just to survive a restart.
        expected, saved = None, None
        with self.db.connect() as conn:
            rows=conn.execute("SELECT result FROM studio_jobs WHERE kind='search' AND item_id=? AND status='complete' ORDER BY created_at DESC LIMIT 10",(item.id,))
            for row in rows:
                for value in json.loads(row['result'] or '{}').get('candidates',[]):
                    if value.get('candidate_id')==identity:
                        expected, saved = value['source_hash'], value
                        break
                if saved:
                    break
        if not expected:raise ValueError('unknown candidate; repeat search')
        if saved.get('source_ref'):
            source, transport = public_source(saved['source_ref'])
            if hashlib.sha256(source.encode()).hexdigest() != expected:
                raise ValueError('candidate identity changed; repeat search')
            value = Candidate(saved['provider'], saved['title'], source,
                              score=saved['score'], exact=saved['exact'],
                              year=saved.get('year'), duration=saved.get('duration'),
                              metadata=saved.get('evidence') or {}, resolver=saved.get('resolver'), transport=transport)
            self.candidates[identity] = (item.id, value)
            return value
        for value in worker._search(item):
            if hashlib.sha256(value.source_url.encode()).hexdigest()==expected:
                self.candidates[identity]=(item.id,value)
                return value
        raise ValueError('candidate no longer available; repeat search')

    def run_one(self, worker) -> bool:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        local = datetime.now(ZoneInfo(self.config.timezone))
        job = self.db.claim_job(allow_automatic=local.hour >= 9 or (local.hour == 0 and local.minute < 45))
        if not job:
            return False
        try:
            result = self.execute(worker, job["kind"], job["item_id"], json.loads(job["payload"]))
            self.db.finish_job(job["id"], result=result)
        except Exception as exc:
            self.db.diagnostic(job["item_id"] or "", job["kind"], "studio", "failed", {"error": type(exc).__name__})
            messages = {
                'unknown candidate; repeat search': '候选记录已过期，请重新检索后试听',
                'candidate no longer available; repeat search': '该候选已无法重新定位，请重新检索或选择其他结果',
                'candidate identity changed; repeat search': '候选身份已变化，请重新检索',
                'invalid selection': '选段需至少 1 秒、最多 180 秒，且开始时间不能为负数',
                'candidate belongs to another item': '该候选属于其他作品，请重新选择',
                'theme changed after preview': '主题在试听后已变化，请重新准备试听再应用',
                'audio exceeds 64 MiB media budget': '音频超过 64 MiB 上限，请选择较小的完整音轨或手动裁剪',
                'complete track exceeds 64 MiB media budget': '完整音轨超过 64 MiB 上限；未自动裁剪，请选择其他音轨',
            }
            # Only known application messages are exposed; upstream exception
            # text can contain signed URLs, cookies or private media paths.
            error = messages.get(str(exc), type(exc).__name__)
            if error == type(exc).__name__ and job['kind'] == 'prepare':
                error = f'试听下载或音频处理失败（{type(exc).__name__}），请重试或选择其他来源'
            self.db.finish_job(job["id"], error=error)
        return True

    def execute(self, worker, kind: str, item_id: str | None, payload: dict):
        if kind == "sync":
            return self.sync(worker)
        if kind == 'register_pending':
            status,count=worker._register_pending()
            return {'status':status,'registered':count}
        item = worker.emby.get_item(item_id)
        if kind == "auto":
            return worker.process(item)
        if kind == "upgrade":
            return worker.migrate_local(dry_run=False, item_id=item.id, limit=1)
        if kind == "search":
            item.search_text = payload.get("keyword")
            results = []
            for candidate in worker._search(item):
                identity = uuid.uuid4().hex
                self.candidates[identity] = (item.id, candidate)
                results.append({"candidate_id": identity, "source_hash": hashlib.sha256(candidate.source_url.encode()).hexdigest(), **candidate.public_dict()})
                try:
                    source, _ = public_source(candidate.source_url)
                    if source == candidate.source_url:
                        results[-1]['source_ref'] = source
                except ValueError:
                    pass  # Never persist direct/signed download URLs.
            return {"candidates": results, "diagnostics": self.db.diagnostics(item.id)}
        if kind in {"prepare", "extract", "trim"}:
            identity = uuid.uuid4().hex
            directory = self.asset(identity)
            directory.mkdir(mode=0o700)
            target = directory/"prepared.mp3"
            meta = {"item_id": item.id, "kind": kind, "created": time.time()}
            if kind == "extract":
                info, detail = worker.prepare_local(item, target)
                meta["extraction"] = detail
                meta['mode'] = 'extracted'
            elif kind == "prepare":
                if payload.get('asset_id'):
                    old = self.asset(payload['asset_id'])
                    previous = json.loads((old/'meta.json').read_text())
                    if previous['item_id'] != item.id:
                        raise ValueError('asset belongs to another item')
                    source = old/'source'
                    if not source.is_file():
                        raise ValueError('original source is unavailable; prepare the candidate again')
                    for key in ('candidate', 'candidate_id', 'source_hash'):
                        if key in previous:
                            meta[key] = previous[key]
                else:
                    candidate = self.candidate(worker, item, payload['candidate_id'])
                    source = worker._fetch_candidate(candidate, directory, item.id)
                    meta['candidate'] = candidate.public_dict()
                    meta['candidate_id'] = payload['candidate_id']
                    meta['source_hash'] = hashlib.sha256(candidate.source_url.encode()).hexdigest()
                shutil.copyfile(source, directory/"source")
                meta['extraction'] = worker.audio.normalize_online(directory/"source", target)
                meta['mode'] = 'full'
            else:
                old = self.asset(payload["asset_id"])
                previous = json.loads((old/"meta.json").read_text())
                if previous["item_id"] != item.id:
                    raise ValueError("asset belongs to another item")
                source = old/'prepared.mp3' if payload.get('basis')=='prepared' else (old/"source" if (old/"source").exists() else old/"prepared.mp3")
                worker.audio.validate_source(source)
                start, end = float(payload.get("start", 0)), float(payload.get("end", 45))
                import math
                source_info = worker.audio.validate_full(source)
                if not all(map(math.isfinite, (start, end))) or start < 0 or end-start < 1 or end > source_info['duration']:
                    raise ValueError("invalid selection")
                shutil.copyfile(source, directory/"source")
                worker.audio._transcode(source, target, start=start, duration=end-start, strip_initial_silence=False)
                meta["selection"] = {"start": start, "end": end}
                meta['mode'] = 'trimmed'
                for key in ('candidate', 'candidate_id', 'source_hash'):
                    if key in previous:
                        meta[key] = previous[key]
            expected_duration = end-start if kind == 'trim' else None
            info = worker.audio.validate_full(target, expected_duration=expected_duration)
            if kind == 'trim':
                # Bounded waveform source; original upload/download remains private.
                worker.audio._transcode(directory/'source', directory/'source_preview.mp3', start=0, duration=600, strip_initial_silence=False)
                meta['source_preview'] = True
            state = self.db.item_state(item.id) or {}
            current = item.directory/"theme.mp3"
            if current.is_symlink() or not contained(str(current),self.config.allowed_path):
                raise PermissionError('theme path is outside managed files')
            meta.update(info=info, expected_sha256=sha256(current) if current.exists() else None,
                        owned=bool(state.get('source_provider') and current.exists() and state.get("output_sha256") == sha256(current)))
            (directory/"meta.json").write_text(json.dumps(meta))
            return {"asset_id": identity, **meta}
        if kind == "apply":
            directory = self.asset(payload["asset_id"])
            meta = json.loads((directory/"meta.json").read_text())
            if meta["item_id"] != item.id:
                raise ValueError("asset belongs to another item")
            prepared = directory/"prepared.mp3"
            info = worker.audio.validate_full(prepared, expected_duration=meta.get('info', {}).get('duration'))
            if meta.get('info', {}).get('sha256') and info['sha256'] != meta['info']['sha256']:
                raise ValueError('prepared audio changed after preview')
            return ThemePublisher(self.config, self.db, worker.audio, worker.emby).apply_manual(
                item, prepared, info, expected_sha256=meta['expected_sha256'], adopt=bool(payload.get('adopt')))
        if kind == "register":
            state = self.db.item_state(item.id) or {}
            target = item.directory/"theme.mp3"
            if not state.get("output_sha256") or not target.exists() or sha256(target) != state["output_sha256"]:
                raise ValueError("not an owned unchanged theme")
            # Explicit control-plane task: one coalesced full scan, never per candidate.
            worker.emby.trigger_library_scan()
            worker.emby.wait_library_scan(self.config.refresh.library_scan_timeout_seconds, self.config.refresh.task_poll_seconds)
            ok = worker.emby.verify_theme_resource(item.id, str(target), state["output_sha256"])
            if ok:
                self.db.record_item(item, "complete", provider=state["source_provider"], score=state["score"], output_path=str(target), output_sha256=state["output_sha256"])
                if state["source_provider"] == "manual":
                    self.db.set_control(item.id, locked=True)
            return {"registered": ok}
        raise ValueError("unknown operation")

    def start_server(self):
        studio = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def reply(self, value, status=200):
                body = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                try:
                    route = urlsplit(self.path).path
                    if route == "/media":
                        return self.reply({"items": studio.media()})
                    if route == "/jobs":
                        return self.reply({"jobs": studio.db.jobs(), "paused": studio.db.get_meta("studio_paused", "false") == "true"})
                    if route == "/status":
                        return self.reply(studio.db.status())
                    if route.startswith("/diagnostics/"):
                        return self.reply({"diagnostics": studio.db.diagnostics(route.rsplit("/", 1)[-1])})
                    if route.startswith("/audio/"):
                        path = studio.asset(route.rsplit("/", 1)[-1])/"prepared.mp3"
                    elif route.startswith('/source-audio/'):
                        directory = studio.asset(route.rsplit('/',1)[-1])
                        meta = json.loads((directory/'meta.json').read_text())
                        path = directory/('prepared.mp3' if meta.get('mode') == 'full' else 'source_preview.mp3')
                    elif route.startswith("/current/"):
                        from .cli import make_worker
                        worker = make_worker(studio.config, studio.db)
                        try:
                            path = worker.emby.get_item(route.rsplit("/", 1)[-1]).directory/"theme.mp3"
                            if not contained(str(path), studio.config.allowed_path):
                                raise ValueError('theme outside allowed media')
                        finally:
                            worker.close()
                    else:
                        return self.reply({"error": "not_found"}, 404)
                    if not path.is_file():
                        return self.reply({"error": "audio_unavailable"}, 404)
                    # Keep one open descriptor across size check and bounded streaming.
                    with path.open("rb") as audio:
                        size = os.fstat(audio.fileno()).st_size
                        if size > MAX_AUDIO_BYTES:
                            return self.reply({"error": "audio_unavailable"}, 404)
                        self.send_response(200)
                        self.send_header("Content-Type", "audio/mpeg")
                        self.send_header("Content-Length", str(size))
                        self.end_headers()
                        remaining = size
                        while remaining:
                            chunk = audio.read(min(STREAM_CHUNK_BYTES, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except Exception as exc:
                    self.reply({"error": type(exc).__name__}, 400)
            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_UPLOAD_BYTES:
                        return self.reply({"error": "invalid_body_size"}, 413)
                    body = self.rfile.read(length)
                    if self.path.startswith("/upload/"):
                        return self.reply({"asset_id": studio.upload(self.path.rsplit("/", 1)[-1], body)})
                    if length > 65536:
                        raise ValueError("JSON too large")
                    payload = json.loads(body)
                    item_id = str(payload.get("item_id", ""))
                    if self.path == "/jobs":
                        return self.reply({"job_id": studio.submit(payload["kind"], item_id or None, payload)})
                    if self.path == '/retry':
                        with studio.db.connect() as conn:
                            row=conn.execute('SELECT * FROM studio_jobs WHERE id=?',(payload.get('job_id'),)).fetchone()
                        if not row or row['status'] not in {'failed','interrupted'} or row['kind'] in {'apply','auto','upgrade'}:
                            raise ValueError('this task needs a new explicit preview/application')
                        return self.reply({'job_id':studio.submit(row['kind'],row['item_id'],json.loads(row['payload']))})
                    if self.path == "/source":
                        return self.reply({"candidate_id": studio.candidate_from_url(item_id, payload["url"])})
                    if self.path == "/lock":
                        if not ID.fullmatch(item_id) or not isinstance(payload.get("locked"), bool):
                            raise ValueError("invalid lock request")
                        with studio.db.item_guard(item_id):
                            studio.db.set_control(item_id, locked=payload["locked"])
                        return self.reply({"locked": payload["locked"]})
                    if self.path == "/pause":
                        studio.db.set_meta("studio_paused", "true" if payload.get("paused") else "false")
                        return self.reply({"ok": True})
                    if self.path == "/feedback":
                        from .db import now
                        if payload.get("verdict") not in {"correct", "wrong", "preferred"} or not re.fullmatch(r"[a-f0-9]{64}", payload.get("candidate_hash", "")):
                            raise ValueError("invalid feedback")
                        with studio.db.connect() as conn:
                            conn.execute("INSERT INTO feedback(emby_id,candidate_hash,verdict,created_at) VALUES(?,?,?,?)", (item_id, payload["candidate_hash"], payload["verdict"], now()))
                        return self.reply({"ok": True})
                    self.reply({"error": "not_found"}, 404)
                except Exception as exc:
                    self.reply({"error": type(exc).__name__}, 400)
        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        path = Path(self.config.control_socket)
        path.parent.mkdir(parents=True, exist_ok=True)
        import fcntl
        self.server_lock = (path.parent/'server.lock').open('a+b')
        fcntl.flock(self.server_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        path.unlink(missing_ok=True)
        server = Server(str(path), Handler)
        os.chmod(path, 0o660)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
