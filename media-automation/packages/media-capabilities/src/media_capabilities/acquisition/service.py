"""Shared acquisition execution. Applications own their protocol and lifecycle."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError, CancelledError
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from threading import RLock
import time
import uuid

from .models import AcquisitionRequest, DownloadTarget, SearchTarget
from .policies import ProfileSettings, select_candidates
from .quality_selection import MediaCandidate
from .selection import quality_key


class SubmissionRegistry:
    """Persist intent before side effects. An unknown result never permits re-submit."""
    def __init__(self, store):
        self.store = store
        self.lock = RLock()

    def read_job(self, task_id):
        with self.lock:
            return self.store.read().get("jobs", {}).get(task_id)

    def update(self, task_id, **values):
        with self.lock:
            state = self.store.read()
            row = state.setdefault("jobs", {}).setdefault(task_id, {"task_id": task_id})
            row.update(values, updated_at=time.time())
            self.store.write(state)
            return deepcopy(row)

    def create(self, task_id, request):
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        with self.lock:
            row = self.read_job(task_id)
            if row:
                if row.get("fingerprint") != fingerprint:
                    raise ValueError("request_id 已用于不同的下载请求")
                return False
            self.update(task_id, status="pending", phase="queued", request=request,
                        fingerprint=fingerprint)
            return True

    def submit(self, task_id, resource_key, facts, callback, authorize=None):
        with self.lock:
            state = self.store.read()
            keys = [resource_key]
            if facts.get('route') == '115_share' and facts.get('candidate_id'):
                from .public_index import Mini4KIndexer
                keys.append('share-candidate:' + Mini4KIndexer.comparable_candidate_id(facts['candidate_id']))
            resources = state.setdefault('resources', {})
            previous_id = next((resources[key] for key in keys if key in resources), None)
            if previous_id:
                for key in keys:
                    resources.setdefault(key, previous_id)
                self.store.write(state)
                previous = state.get("jobs", {}).get(previous_id, {})
                return {**deepcopy(previous), "task_id": task_id,
                        "original_task_id": previous_id, "reused": True}
            if authorize:
                authorize()
            row = state.setdefault("jobs", {}).setdefault(task_id, {"task_id": task_id})
            row.update(facts, status="pending", phase="submitting", updated_at=time.time())
            for key in keys:
                resources[key] = task_id
            self.store.write(state)
        try:
            receipt = callback()
        except Exception:
            # Exception text can contain signed URLs or cookies: keep only our message.
            receipt = {"status": "pending", "reason": "提交响应不明，按资源标识对账，不自动重交"}
        status = receipt.get("status", "pending")
        return self.update(task_id, **receipt, phase="submitted" if status == "submitted"
                           else "rejected" if status == "failed" else "submitting")


class AcquisitionService:
    def __init__(self, identities, sources, downloader, registry,
                 profiles: ProfileSettings = ProfileSettings(), search_timeout=60, public_only=False):
        self.identities, self.downloader, self.registry = identities, downloader, registry
        self.sources = {s.source_id: s for s in sources}
        self.public_only = public_only
        self.profiles, self.search_timeout = profiles, search_timeout
        self.io = ThreadPoolExecutor(max_workers=4, thread_name_prefix="acquisition-source")
        self.workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="acquisition-job")
        self.lock = RLock()
        self.sessions, self.references, self.cache, self.inflight, self.jobs = {}, {}, {}, {}, {}
        self.closed = False

    @staticmethod
    def identity_dict(media):
        return {k: getattr(media, k) for k in ("title", "year", "media_type", "tmdb_id", "imdb_id", "ended")}

    def _target(self, request, *, search_only=False):
        if request.candidate_id:
            with self.lock:
                entry = self.references.get(request.candidate_id)
            if not entry or entry[3] < time.monotonic():
                raise ValueError("候选引用已过期，请重新搜索")
            original = entry[2]
            # A reference freezes identity, not permission to change its target silently.
            if (request.scope, request.season, request.episode) != (original.scope, original.season, original.episode):
                raise ValueError("候选引用的下载范围不匹配，请按目标范围重新搜索")
            if not search_only and isinstance(entry[1], SearchTarget):
                raise ValueError("媒体身份尚未核实，请提供 TMDB/IMDb ID 重新搜索后下载")
            return entry[1], [entry[0]], []
        try:
            identities = self.identities.identify(request)
        except Exception:
            if not search_only or not request.title.strip():
                raise
            identities = []
        if not identities and search_only and request.title.strip():
            return SearchTarget.from_request(request), [], []
        if len(identities) != 1 or not identities[0].exact_match:
            return None, [], [self.identity_dict(m) for m in identities]
        return DownloadTarget.build(identities[0], request), [], []

    def _fetch(self, source_id, target, cursor=None):
        key = json.dumps((source_id, asdict(target.media), target.scope,
                          sorted(target.expected), cursor), sort_keys=True)
        now = time.monotonic()
        with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                from concurrent.futures import Future
                future = Future()
                future.set_result(cached[1])
                return future
            if key in self.inflight:
                return self.inflight[key]
            future = self.io.submit(self.sources[source_id].search, target, cursor)
            self.inflight[key] = future
        def completed(result):
            with self.lock:
                self.inflight.pop(key, None)
                try:
                    page = result.result()
                    if page.status in ("OK", "NO_RESULTS"):
                        ttl = 300 if page.status == "OK" else 30
                        if len(self.cache) >= 256:
                            self.cache.pop(next(iter(self.cache)))
                        self.cache[key] = (time.monotonic() + ttl, page)
                except Exception:
                    pass
        future.add_done_callback(completed)
        return future

    def start_search(self, data):
        request = AcquisitionRequest.parse(data)
        session_id = uuid.uuid4().hex
        with self.lock:
            now = time.monotonic()
            expired = [key for key, value in self.sessions.items() if value["expires"] < now]
            for key in expired:
                self.sessions.pop(key, None)
            self.references = {k: v for k, v in self.references.items() if v[3] > now}
            if len(self.sessions) >= 128:
                raise ValueError("查询会话已满，请稍后重试")
            self.sessions[session_id] = {"session_id": session_id, "status": "pending",
                "candidates": [], "sources": {}, "choices": [], "expires": now + 900,
                "started": now, "request": request}
        self.workers.submit(self._search, session_id)
        return self.search_status(session_id)

    def _search(self, session_id):
        session = self.sessions[session_id]
        try:
            target, explicit, choices = self._target(session["request"], search_only=True)
            if target is None:
                with self.lock:
                    session.update(status="needs_selection" if choices else "no_match", choices=choices)
                return
            with self.lock:
                session.update(target=target, media=self.identity_dict(target.media),
                               scope=target.scope, expected_count=None if isinstance(target, SearchTarget) else len(target.expected),
                               identity_status='unverified' if isinstance(target, SearchTarget) else 'verified')
                if isinstance(target, SearchTarget):
                    session['warnings'] = ['媒体身份识别未成功，已按名称和年份直接查询；下载前仍需核实媒体身份']
                session["sources"] = {s: {"status": "pending"} for s in self.sources}
            futures = {self._fetch(s, target): s for s in self.sources}
            try:
                for future in as_completed(futures, timeout=self.search_timeout):
                    source = futures[future]
                    self._publish_page(session_id, source, future)
            except TimeoutError:
                with self.lock:
                    for source, value in session["sources"].items():
                        if value["status"] == "pending":
                            value.update(status="UNAVAILABLE", reason="站点查询超时")
            with self.lock:
                session.update(status="complete", elapsed_ms=round((time.monotonic()-session["started"])*1000))
        except Exception as exc:
            with self.lock:
                session.update(status="failed", reason=str(exc) if isinstance(exc, ValueError)
                               else "媒体识别或查询服务不可用")

    def _publish_page(self, session_id, source, future):
        session = self.sessions[session_id]
        try:
            page = future.result()
        except Exception:
            with self.lock:
                session["sources"][source] = {"status": "UNAVAILABLE", "reason": "站点查询失败"}
            return
        with self.lock:
            aggregate_status = "OK" if page.status == "NO_RESULTS" and any(
                c['source_id'] == source for c in session['candidates']) else page.status
            session["sources"][source] = {"status": aggregate_status, "reason": page.reason,
                "has_more": bool(page.next_cursor), "cursor": page.next_cursor,
                "elapsed_ms": round((time.monotonic()-session["started"])*1000)}
            existing = session.setdefault("native_keys", set())
            for candidate in page.candidates:
                key = (candidate.source_id, candidate.candidate_id)
                if key in existing:
                    continue
                existing.add(key)
                ref = uuid.uuid4().hex
                self.references[ref] = (candidate, session["target"], session["request"], session["expires"])
                session["candidates"].append({**candidate.public_dict(), "candidate_id": ref})
            if session["candidates"] and "first_result_ms" not in session:
                session["first_result_ms"] = round((time.monotonic()-session["started"])*1000)

    def search_status(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            if not session or session["expires"] < time.monotonic():
                raise ValueError("查询会话不存在或已过期")
            result = {k: deepcopy(v) for k, v in session.items() if k not in
                      ("request", "target", "native_keys", "started", "expires")}
            for source in result["sources"].values():
                source.pop("cursor", None)
            return result

    def more(self, session_id, source_id):
        with self.lock:
            self.search_status(session_id)
            session = self.sessions[session_id]
            value = session["sources"].get(source_id)
            if not value or not value.get("cursor") or value["status"] == "pending":
                raise ValueError("该站点没有可继续读取的分页")
            cursor = value["cursor"]
            value["status"] = "pending"
            session["status"] = "pending"
        def load():
            future = self._fetch(source_id, session["target"], cursor)
            try:
                future.result(timeout=self.search_timeout)
                self._publish_page(session_id, source_id, future)
            except Exception:
                with self.lock:
                    session["sources"][source_id] = {"status": "UNAVAILABLE", "reason": "分页查询失败"}
            with self.lock:
                session["status"] = "complete"
        self.workers.submit(load)
        return self.search_status(session_id)

    def download(self, data, wait_timeout=120):
        request = AcquisitionRequest.parse(data)
        task_id = request.request_id or uuid.uuid4().hex
        payload = asdict(request)
        payload["request_id"] = task_id
        with self.lock:
            created = self.registry.create(task_id, payload)
            if created:
                self.jobs[task_id] = self.workers.submit(self._acquire, task_id, request)
            future = self.jobs.get(task_id)
        if future:
            try:
                future.result(timeout=max(0, min(wait_timeout, 120)))
            except TimeoutError:
                return self._receipt(self.registry.read_job(task_id))
            except CancelledError:
                self.registry.update(task_id, status='failed', reason='服务停止，未提交下载')
        return self.status(task_id)

    @staticmethod
    def _receipt(row):
        if not row:
            return {"status": "not_found"}
        # Explicit allow-list: native links, requests and saved internal facts stay private.
        keys = ("task_id", "status", "phase", "reason", "media", "scope", "policy", "route",
                "effective_policy",
                "season", "episode", "expected_count",
                "resource", "info_hash", "download_hash", "warnings", "sources", "timing",
                "progress", "original_task_id", "reused", "choices")
        return {k: deepcopy(row[k]) for k in keys if k in row}

    def _acquire(self, task_id, request):
        started = time.monotonic()
        try:
            target, explicit, choices = self._target(request)
            if target is None:
                self.registry.update(task_id, status="needs_selection" if choices else "no_match",
                                     phase="identified", choices=choices)
                return
            self.registry.update(task_id, phase="searching", media=self.identity_dict(target.media),
                                 scope=target.scope, policy=request.policy)
            candidates, states, warnings = list(explicit), {}, []
            if not explicit:
                enabled_sources = [s for s, adapter in self.sources.items()
                                   if not self.public_only or getattr(adapter, 'public_source', False)]
                states.update({s: {'status': 'SKIPPED', 'reason': '仅公网自动选源已开启'}
                               for s in self.sources if s not in enabled_sources})
                pending = {self._fetch(s, target): s for s in enabled_sources}
                deadline = time.monotonic() + self.search_timeout
                # Follow all pages lazily; page results never fetch torrent metadata.
                pages = {s: 0 for s in self.sources}
                counts = {s: 0 for s in self.sources}
                while pending and time.monotonic() < deadline:
                    try:
                        done = next(as_completed(pending, timeout=max(0.01, deadline-time.monotonic())))
                    except TimeoutError:
                        break
                    source = pending.pop(done)
                    try:
                        page = done.result()
                    except Exception:
                        states[source] = {"status": "UNAVAILABLE"}
                        continue
                    counts[source] += len(page.candidates)
                    states[source] = {"status": 'OK' if page.status == 'NO_RESULTS' and counts[source]
                                      else page.status, "has_more": bool(page.next_cursor),
                                      "reason": page.reason}
                    candidates.extend(page.candidates)
                    pages[source] += 1
                    if page.next_cursor and page.status in ("OK", "NO_RESULTS") and pages[source] < 12:
                        pending[self._fetch(source, target, page.next_cursor)] = source
                for source in pending.values():
                    states[source] = {"status": "UNAVAILABLE", "reason": "查询预算耗尽"}
            if any(v.get("status") not in ("OK", "NO_RESULTS", "SKIPPED") or v.get("has_more") for v in states.values()):
                warnings.append("部分站点查询失败或分页未完成，已从核实候选中选源")
            candidates = list({(c.source_id, c.candidate_id): c for c in candidates}.values())
            candidates.sort(key=lambda c: (MediaCandidate('pt', c.title, 1, 1, c.candidate_id).tier,
                quality_key(c.title, c.seeders), c.size_bytes or 0), reverse=True)
            if request.policy == 'balanced' and not explicit:
                candidates = [c for c in candidates if not quality_key(c.title)[0]
                              and quality_key(c.title)[1] in (1080, 2160)]
            if request.policy == "subtitle":
                candidates.sort(key=lambda c: c.subtitles.chinese, reverse=True)
            self.registry.update(task_id, phase="verifying", sources=states)
            verified, rejected = [], []
            verification_started = time.monotonic()
            for candidate in candidates:
                # Expensive inspection is bounded and only happens for a download request.
                if time.monotonic()-verification_started >= 60:
                    warnings.append("候选预检预算耗尽，剩余候选尚未核实")
                    break
                # A lower quality tier cannot overturn a verified higher tier.
                if verified and request.policy == "quality":
                    upper = MediaCandidate("pt", candidate.title, 1, 1, candidate.candidate_id).tier
                    if upper < max(c.tier for c in verified):
                        break
                try:
                    resolved = self.sources[candidate.source_id].resolve(candidate, target)
                    verified.extend(c for c in resolved if explicit or not self.public_only or c.public)
                except Exception as exc:
                    rejected.append(str(exc) if isinstance(exc, ValueError) else "候选核验服务不可用")
            ranked, fallback = select_candidates(verified, target, 'quality' if explicit else request.policy, self.profiles)
            warnings.extend(fallback)
            if rejected:
                warnings.append("部分候选未通过核验：" + "; ".join(dict.fromkeys(rejected))[:300])
            if not ranked:
                queried = [v for v in states.values() if v.get('status') != 'SKIPPED']
                unavailable = bool(queried) and all(v.get('status') not in ('OK', 'NO_RESULTS') for v in queried)
                self.registry.update(task_id, status="unavailable" if unavailable else "no_match",
                    phase="verified", warnings=warnings,
                    reason="所有站点查询均不可用" if unavailable else "没有满足目标范围、下载路由和策略的已核实资源")
                return
            chosen = ranked[0]
            if target.scope == "series" and chosen.source == "115_share":
                raise ValueError("整剧必须使用单一完整 BT 资源")
            facts = {"media": self.identity_dict(target.media), "scope": target.scope,
                "season": request.season if target.scope in ('season', 'episode') else None,
                "episode": request.episode if target.scope == 'episode' else None,
                "expected_count": len(target.expected),
                "policy": 'manual' if explicit else request.policy, "route": chosen.source, "info_hash": chosen.info_hash,
                "effective_policy": 'manual' if explicit else 'balanced' if fallback else request.policy,
                "media_type": target.media.media_type,
                "candidate_id": chosen.candidate_id,
                "resource": {"title": chosen.title, "video_bytes": chosen.video_bytes,
                             "total_bytes": chosen.total_bytes,
                             "subtitles": chosen.evidence.get("subtitles", {})},
                "warnings": warnings, "sources": states,
                "target_path": chosen.evidence.get("target_path", ""),
                "root_names": chosen.evidence.get("root_names", []),
                "timing": {"search_ms": round((verification_started-started)*1000),
                           "inspection_ms": round((time.monotonic()-verification_started)*1000)},
                "reason": "已核实用户指定的候选资源" if explicit else
                    "按" + {"quality": "质量", "subtitle": "字幕", "balanced": "均衡"}[request.policy] + "策略选择已核实资源"}
            key = chosen.info_hash or chosen.evidence.get("share_key")
            if not key:
                raise ValueError("无法确认资源幂等标识")
            if self.closed:
                raise ValueError('服务停止，未提交下载')
            receipt = self.registry.submit(task_id, key, facts, lambda: self.downloader.submit(chosen, target),
                authorize=getattr(self.downloader, 'guard_submission', None))
            if receipt.get("reused"):
                self.registry.update(task_id, **{k: v for k, v in receipt.items()
                    if k not in ("task_id", "request", "fingerprint", "updated_at")})
        except TimeoutError:
            self.registry.update(task_id, status="no_match", phase="searching",
                                 reason="站点查询超时，请稍后用新的请求重试")
        except Exception as exc:
            self.registry.update(task_id, status="failed", reason=str(exc) if isinstance(exc, ValueError)
                                 else "获取资源失败，未自动重试提交")

    def status(self, task_id):
        row = self.registry.read_job(task_id)
        if row and row.get("original_task_id"):
            original = self.registry.read_job(row["original_task_id"])
            if original:
                row = {**original, "task_id": task_id, "original_task_id": row["original_task_id"], "reused": True}
        if row and row.get("phase") in ("submitting", "submitted"):
            try:
                result = self.downloader.status(row)
                if result:
                    self.registry.update(row.get("original_task_id", task_id), **result)
                    row.update(result)
            except Exception:
                pass  # Preserve the receipt; a status outage is not evidence of absence.
        elif row and row.get("status") == "pending" and task_id not in self.jobs:
            row = self.registry.update(task_id, status="failed", reason="宿主重启中断了提交前处理，可用新的请求重试")
        return self._receipt(row)

    def close(self):
        self.closed = True
        self.workers.shutdown(wait=False, cancel_futures=True)
        self.io.shutdown(wait=False, cancel_futures=True)
