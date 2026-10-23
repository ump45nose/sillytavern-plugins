"""Candidate policies and one durable submit path; host lifecycle stays in the plugin."""
from concurrent.futures import ThreadPoolExecutor

from app.chain.download import DownloadChain
from app.chain.search import SearchChain
from app.log import logger
from app.schemas.types import MediaType
from app.utils.http import RequestUtils
from media_capabilities.acquisition.runtime import HostUnavailable

from media_capabilities.acquisition.models import DownloadTarget, MediaIdentity, ResourceCandidate
from media_capabilities.acquisition.resolution import pt_candidate, public_candidates
from media_capabilities.acquisition.policies import subtitle_evidence
from .p115_task_adapter import ShareEvidence
from .public_index import IndexStatus, MediaQuery, Mini4KIndexer
from .quality_selection import MediaCandidate, rank_candidates
from .selection import normalize_title, quality_key


def store_reused_receipt(self, film_id, decision, records, receipt):
    """A shared hash keeps its original route and destination, including uncertain jobs."""
    if not receipt or not receipt.get('reused'):
        return False
    route = receipt.get('route') or decision['route']
    accepted = receipt.get('status') in ('submitted', 'completed')
    actual = {key: receipt[key] for key in ('info_hash', 'target_path') if key in receipt}
    actual.update(route=route, download_hash=(receipt.get('download_hash') or receipt.get('info_hash') or '')
        if route == 'pt' and accepted else '', task_state='SUBMITTED' if accepted else 'SUBMITTING',
        status=('等待入库' if route == 'pt' else '115 下载中' if route == 'public_bt' else '等待整理')
            if accepted else '提交结果待核实', reason='复用公共宿主已有回执，按原下载路由对账')
    if route == '115_share':
        actual['share_root_names'] = receipt.get('root_names') or []
    self._store(records, film_id, **{**decision, **actual})
    return True


def submit_pt(self, film_id: int, context, content: bytes, decision: dict, records: dict):
    """One submit boundary for both policies, with durable intent and uncertain receipt."""
    try:
        runtime = self._capabilities()
        runtime.ensure_active()
    except HostUnavailable as exc:
        self._store(records, film_id, **decision, status='路由暂停', reason=str(exc))
        return
    decision = {**decision, 'route': 'pt', 'download_hash': ''}
    self._store(records, film_id, **decision, task_state='SUBMITTING',
                status='提交中', reason='已保存幂等键，正在提交任务')
    try:
        from uuid import uuid4
        receipt = runtime.submit_pt('legacy-' + uuid4().hex, decision['info_hash'],
            context, content, source='FilmWatchlist')
        if store_reused_receipt(self, film_id, decision, records, receipt):
            return
        download_hash = receipt.get('download_hash') if receipt.get('status') in ('submitted', 'completed') else ''
    except HostUnavailable as exc:
        self._store(records, film_id, task_state='', status='路由暂停', reason=str(exc))
        return
    except Exception as exc:
        self._store(records, film_id, status='提交结果待核实',
                    reason=f'M-Team 提交结果不明：{type(exc).__name__}')
        return
    if not download_hash:
        self._store(records, film_id, status='提交结果待核实',
                    reason='M-Team 未返回受理回执，稍后按 info-hash 对账')
        return
    # Do not put this write inside a candidate retry catch: the external side effect happened.
    self._store(records, film_id, **{**decision, 'download_hash': download_hash},
                task_state='SUBMITTED', status='等待入库', reason='M-Team 已提交下载')


def download_target(media_type, expected, season=None):
    kind = 'movie' if media_type == MediaType.MOVIE.value else 'tv'
    return DownloadTarget(MediaIdentity('', kind), 'movie' if kind == 'movie' else 'season',
                          frozenset((season or 1, episode) for episode in expected or ()))


def process_unified(self, film_id: int, item: dict, media, media_type: str,
                     expected: set[int] | None, common: dict, records: dict):
    """Search both sources, verify playable bytes, then route one candidate."""
    target = download_target(media_type, expected, common['season'])
    query = MediaQuery(
        title=str(item.get('title') or ''),
        aliases=tuple(dict.fromkeys(str(name) for name in
                   (getattr(media, 'original_title', None), *(getattr(media, 'names', None) or []))
                   if name and normalize_title(str(name)) != normalize_title(str(item.get('title') or ''))))[:3],
        year=int(item['release_year']) if item.get('release_year') else None,
        country=item.get('country'), media_type='movie' if media_type == MediaType.MOVIE.value else 'tv',
        tmdb_id=getattr(media, 'tmdb_id', None), season=common['season'],
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        public_future = executor.submit(self._search_public, query)
        pt_future = executor.submit(SearchChain().process, mediainfo=media,
                                    sites=[self._site_id], rule_groups=[]) if not self._public_only else None
        try:
            public_status, public_items, public_reason = public_future.result()
        except Exception as exc:
            public_status, public_items, public_reason = IndexStatus.UNAVAILABLE, [], type(exc).__name__
        try:
            contexts = (pt_future.result() or []) if pt_future else []
        except Exception as exc:
            self._store(records, film_id, **common, status='PT 查询暂停',
                        reason=f'M-Team 搜索失败：{type(exc).__name__}')
            return
    if public_status not in (IndexStatus.OK, IndexStatus.NO_RESULTS):
        self._store(records, film_id, **common, status='公网查询暂停',
                    reason=f'{public_status.value}：{public_reason or "公网不可查询"}')
        return
    rejected: list[str] = []
    uncertain = False
    unresolved_items: list = []
    candidates: list[MediaCandidate] = []
    failed_ids = {Mini4KIndexer.comparable_candidate_id(value) for value in
                  (records.get(str(film_id)) or {}).get('failed_candidates') or []}
    failed_hashes = set((records.get(str(film_id)) or {}).get('failed_hashes') or [])
    contexts = [context for context in contexts if context.torrent_info
                and context.torrent_info.site == self._site_id
                and context.torrent_info.category == media_type]
    contexts.sort(key=lambda context: quality_key(context.torrent_info.title,
                  context.torrent_info.seeders), reverse=True)
    for context in contexts[:12]:
        torrent = context.torrent_info
        try:
            content, _, _ = DownloadChain().download_torrent(torrent, source='FilmWatchlist')
            if not content:
                raise ValueError('种子获取失败')
            candidates.append(pt_candidate(content, torrent.title, torrent.page_url, context, target))
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append(f'{torrent.title}: {exc}')
        except Exception as exc:
            rejected.append(f'{torrent.title}: {type(exc).__name__}')
    # Preflight the same quality tiers used by the final selector. Listed size
    # only prioritizes inspection; selection still uses verified video bytes.
    public_items.sort(key=lambda candidate: (
        MediaCandidate('public_bt', candidate.title, 1, 1, candidate.candidate_id).tier,
        candidate.size_bytes or 0, quality_key(candidate.title)), reverse=True)
    eligible_public = [indexed for indexed in public_items
                       if Mini4KIndexer.comparable_candidate_id(indexed.candidate_id) not in failed_ids]
    adapter = self._p115()
    for indexed in eligible_public[:8]:
        resolved = self._indexer().resolve(indexed.candidate_id)
        if resolved.status not in (IndexStatus.OK, IndexStatus.LINK_INVALID):
            uncertain = True
            unresolved_items.append(indexed)
            rejected.append(f'{indexed.title}: {resolved.status.value}')
            continue
        if resolved.status != IndexStatus.OK:
            rejected.append(f'{indexed.title}: 链接失效')
            continue
        resource = ResourceCandidate(indexed.candidate_id, 'mini4k', indexed.title,
                                     subtitles=subtitle_evidence(indexed.quality_text))
        verified, errors = public_candidates(resolved.links, resource, target, lambda: adapter,
                                             share_enabled=self._share_115_enabled)
        for candidate in verified:
            if candidate.info_hash and candidate.info_hash in failed_hashes:
                rejected.append(f'{indexed.title}: 此 info-hash 的 115 任务之前已失败')
            else:
                candidates.append(candidate)
        for exc in errors:
            if not isinstance(exc, (ValueError, RuntimeError)) or '元数据' in str(exc) or '客户端' in str(exc):
                uncertain = True
                unresolved_items.append(indexed)
            rejected.append(f'{indexed.title}: {exc if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__}')
    unique_candidates = {}
    for candidate in candidates:
        key = (candidate.source, candidate.info_hash or candidate.candidate_id)
        if key not in unique_candidates or candidate.video_bytes > unique_candidates[key].video_bytes:
            unique_candidates[key] = candidate
    ranked = rank_candidates(list(unique_candidates.values()), self._near_size_ratio)
    if not ranked:
        self._store(records, film_id, **common,
                    status='待核实' if uncertain or len(eligible_public) > 8 else '无可用资源',
                    reason=(rejected[0] if rejected else '没有匹配资源'), rejected=rejected[:5])
        return
    chosen = ranked[0]
    def can_change_choice(indexed) -> bool:
        tier = MediaCandidate('public_bt', indexed.title, 1, 1,
                              indexed.candidate_id).tier
        if tier != chosen.tier:
            return tier > chosen.tier
        # Listed total size is only an upper bound for playable video bytes.
        return (indexed.size_bytes is None or
                indexed.size_bytes >= chosen.video_bytes * (1 - self._near_size_ratio))

    if any(can_change_choice(indexed) for indexed in
           (*unresolved_items, *eligible_public[8:])):
        self._store(records, film_id, **common, status='待核实',
                    reason='同档或更高档的公网候选尚未核实，暂停自动提交',
                    rejected=rejected[:5])
        return
    decision = {**common, 'torrent_title': chosen.title,
                'candidate_id': chosen.candidate_id, 'route': chosen.source,
                'info_hash': chosen.info_hash, 'video_bytes': chosen.video_bytes,
                'quality_tier': chosen.tier,
                'download_hash': '', 'strm_ready': False,
                'non_remux': quality_key(chosen.title)[0] == 0,
                'rejected': rejected[:5]}
    decision['target_path'] = adapter.target_path(media_type) if chosen.public else ''
    if chosen.source == '115_share':
        decision['share_root_names'] = list(chosen.evidence['root_names'])
    if self._dry_run:
        self._store(records, film_id, **decision, status='预览',
                    reason=f'同档按视频体积裁决：{chosen.source}，{chosen.video_bytes / 1024**3:.2f} GiB')
        return
    try:
        self._capabilities().ensure_active()
    except HostUnavailable as exc:
        self._store(records, film_id, **decision, status='路由暂停', reason=str(exc))
        return
    if chosen.public and not self._p115_route_enabled:
        self._store(records, film_id, **decision, status='路由暂停',
                    reason='公网候选胜出，但 115 自动路由尚未启用')
        return
    if chosen.public:
        try:
            adapter.validate_target(media_type)
        except Exception as exc:
            self._store(records, film_id, **decision, status='路由暂停',
                        reason=f'115 目标目录或客户端不可用：{type(exc).__name__}')
            return
    if chosen.source == '115_share' and adapter.cloud_items(
            media_type, tuple(chosen.evidence['root_names'])):
        self._store(records, film_id, **decision, status='待核实',
                    reason='115 目标目录已有同名文件，避免重复转存')
        return
    if chosen.source == 'pt':
        self._submit_pt(film_id, chosen.context, chosen.torrent_content, decision, records)
        return
    decision['local_strm_root'] = getattr(adapter, 'local_strm_root', '/Media/115_strm')
    adapter.submission_candidate_id = chosen.candidate_id
    self._store(records, film_id, **decision, status='提交中',
                task_state='SUBMITTING', reason='已保存幂等键，正在提交任务')
    if chosen.source == 'public_bt':
        try:
            existing = adapter.offline_task(chosen.info_hash)
            accepted = bool(existing) or adapter.submit_magnet(chosen.link, media_type)
        except HostUnavailable as exc:
            self._store(records, film_id, task_state='', status='路由暂停', reason=str(exc))
            return
        if store_reused_receipt(self, film_id, decision, records, getattr(adapter, 'last_submission_receipt', None)):
            return
        if not accepted:
            self._store(records, film_id, **decision, status='提交结果待核实',
                        reason='115 未确认接收磁力，稍后按 info-hash 对账')
            return
        self._store(records, film_id, **decision, task_state='SUBMITTED',
                    status='115 下载中', reason=f'已提交到 {adapter.target_path(media_type)}')
        return
    share = ShareEvidence(chosen.files, chosen.video_bytes, chosen.total_bytes,
                          chosen.file_ids, tuple(chosen.evidence['root_names']))
    try:
        accepted = adapter.submit_share(chosen.link, media_type, share)
    except HostUnavailable as exc:
        self._store(records, film_id, task_state='', status='路由暂停', reason=str(exc))
        return
    if store_reused_receipt(self, film_id, decision, records, getattr(adapter, 'last_submission_receipt', None)):
        return
    if not accepted:
        self._store(records, film_id, **decision, status='提交结果待核实',
                    reason='115 分享转存结果不明，等待目标目录对账')
        return
    self._store(records, film_id, **{**decision, 'share_root_names': list(share.root_names)},
                task_state='SUBMITTED', status='等待整理',
                reason=f'115 分享已转存到 {adapter.target_path(media_type)}')


def process_one(self, item: dict, client: RequestUtils, records: dict):
    """执行一条记录的识别、去重、质量选择和可选入队。"""
    film_id = int(item["id"])
    title = str(item.get("title") or "")
    old = records.get(str(film_id)) or {}
    if self._resume_record(film_id, old, records, client):
        return
    hint = self._identity_hints.get(str(film_id)) or {
        "media_type": old.get("media_type"), "tmdb_id": old.get("tmdb_id"),
        "douban_id": old.get("douban_id"),
    }
    media, season, error = self._identify(item, hint)
    if error:
        if error == "MoviePilot 元数据搜索暂未返回结果" and item.get("release_year") and not self._public_only:
            try:
                site_results = SearchChain().search_by_title(
                    f"{title} {item['release_year']}", sites=[self._site_id]) or []
                if site_results:
                    error = f"M-Team 有 {len(site_results)} 个标题搜索结果；媒体身份未确认，稍后重试"
            except Exception as exc:
                logger.warning(f"片单 {film_id} 站点标题搜索检查失败：{type(exc).__name__}")
        if old.get('status') == '已完成':
            self._store(records, film_id, source_error=error, reason=error)
        else:
            self._store(records, film_id, title=title, status="跳过", reason=error)
        return
    media_type = media.type.value if isinstance(media.type, MediaType) else media.type
    media_key = f"{media_type}:{media.tmdb_id or media.douban_id}:S{season or 0:02d}"
    common = {"title": title, "media_key": media_key, "media_type": media_type,
              "season": season, "tmdb_id": media.tmdb_id, "douban_id": media.douban_id,
              "media_snapshot": self._media_snapshot(media, season),
              "source_snapshot": self._source_snapshot(item)}
    if old.get('status') == '已完成' and old.get('media_key') != media_key:
        history = list(old.get('completed_history') or [])
        history.append({key: value for key, value in old.items() if key != 'completed_history'})
        self._store(records, film_id, **common, completed_history=history,
                    task_state='', route='', candidate_id='', download_hash='', info_hash='',
                    target_path='', local_strm_root='', share_root_names=[], cloud_root_ids=[],
                    strm_ready=False, library_ready=False, failed_candidates=[], failed_hashes=[],
                    torrent_title='', torrent_url='', video_bytes=0, quality_tier=None,
                    rejected=[], non_remux=False, source_error='', status='待处理', reason='')
        old = records[str(film_id)]
    if self._library_complete(media, season):
        if self._dry_run:
            self._store(records, film_id, **common, status="预览", reason="媒体库已存在；正式运行时写回")
        else:
            self._store(records, film_id, **common, library_ready=True)
            ok, reason = self._writeback_record(client, film_id, records[str(film_id)])
            self._store(records, film_id, **common, status="已完成" if ok else "待写回", reason=reason)
        return
    if old.get('library_ready'):
        # Even a library-only completion (no downloader handle) can be reopened.
        self._store(records, film_id, library_ready=False)
    if old.get('media_key') == media_key and (old.get('download_hash') or
            old.get('task_state') in ('SUBMITTING', 'SUBMITTED')):
        # A reopened completed source is not permission to duplicate its accepted task.
        self._resume_record(film_id, {**old, 'status': '等待入库', 'library_ready': False}, records, client)
        return
    if self._other_download(media, season):
        self._store(records, film_id, **common, status="等待入库", reason="MoviePilot 已有同媒体下载历史")
        return
    expected = self._expected_episodes(media, season)
    if season is not None and not expected:
        self._store(records, film_id, **common, status="跳过", reason="无法核实第一季集数")
        return
    if not self._dry_run:
        try:
            self._capabilities().ensure_active()
        except HostUnavailable as exc:
            self._store(records, film_id, **common, status='路由暂停', reason=str(exc))
            return
    if any(row.get('media_key') == media_key and key != str(film_id)
           and self._pending_record(row) for key, row in records.items()):
        self._store(records, film_id, **common, status='等待入库',
                    reason='同一媒体的其他片单记录已有任务')
        return
    if self._public_selection_enabled or self._public_only:
        self._process_unified(film_id, item, media, media_type, expected, common, records)
        return
    contexts = SearchChain().process(mediainfo=media, sites=[self._site_id], rule_groups=[]) or []
    contexts = [context for context in contexts
                if context.torrent_info and context.torrent_info.site == self._site_id
                and context.torrent_info.category == media_type]
    contexts.sort(key=lambda context: quality_key(context.torrent_info.title,
                  context.torrent_info.seeders), reverse=True)
    rejected = []
    for context in contexts:
        torrent = context.torrent_info
        try:
            content, _, _ = DownloadChain().download_torrent(torrent, source="FilmWatchlist")
            candidate = pt_candidate(content, torrent.title, torrent.page_url, context,
                                     download_target(media_type, expected, season))
            non_remux = quality_key(torrent.title)[0] == 0
            chosen = {**common, "torrent_title": torrent.title,
                      "torrent_url": torrent.page_url, "non_remux": non_remux,
                      "rejected": rejected[:5]}
            if self._dry_run:
                self._store(records, film_id, **chosen, status="预览",
                            reason="非 Remux 回退" if non_remux else "Remux 优先")
                return
            # Compute the stable task identity before writing intent or submitting.
            chosen.update(info_hash=candidate.info_hash, candidate_id=candidate.candidate_id)
        except Exception as exc:
            rejected.append(f"{torrent.title}: {type(exc).__name__}")
            logger.warning(f"片单 {film_id} 候选处理失败：{type(exc).__name__}")
            continue
        self._submit_pt(film_id, context, content, chosen, records)
        return
    self._store(records, film_id, **common, status="等待资源" if not rejected else "无可用资源",
                torrent_title="", reason="无匹配资源" if not rejected else rejected[0],
                rejected=rejected[:5])
