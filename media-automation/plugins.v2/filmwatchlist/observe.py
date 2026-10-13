"""Recover saved tasks and safely write results back, independent of source enumeration."""
from app.chain.media import MediaChain
from app.core.context import MediaInfo
from app.schemas.types import MediaType
from app.utils.http import RequestUtils

from .media_types import normalize_media_type


def writeback_record(self, client: RequestUtils, film_id: int, record: dict) -> tuple[bool, str]:
    """Task recovery is independent; writing a mutable source needs a fresh identity check."""
    try:
        client = client or self._client()
        response = client.get_res(f'{self._api_url}/v1/films/{film_id}')
        if response is None or response.status_code != 200:
            return False, '原任务已入库；片单身份暂不可查，稍后重试写回'
        current = response.json()
        if not isinstance(current, dict) or not current.get('title'):
            return False, '片单身份响应无效，暂停写回'
        same = bool(record.get('source_snapshot')) and (
            self._source_snapshot(current) == record['source_snapshot'])
        if not same:
            # Older records lack source fields, and aliases may change presentation.
            # Re-identify by the saved IDs only for this writeback check, never before recovery.
            frozen = record.get('media_snapshot') or record
            media, season, error = self._identify(current, {
                'media_type': frozen.get('media_type'), 'tmdb_id': frozen.get('tmdb_id'),
                'douban_id': frozen.get('douban_id')})
            same = bool(not error and media and season == frozen.get('season')
                        and normalize_media_type(media.type) == normalize_media_type(frozen.get('media_type'))
                        and ((frozen.get('tmdb_id') and media.tmdb_id == frozen['tmdb_id'])
                             or (frozen.get('douban_id') and media.douban_id == frozen['douban_id'])))
        if not same:
            return False, '片单身份已改变；原任务已入库，暂停写回等待人工核实'
        # A different returned numeric ID can be a documented Favsync alias.
        return self._mark_downloaded(client, film_id)
    except Exception as exc:
        return False, f'片单身份核验失败：{type(exc).__name__}'


def resume_record(self, film_id: int, old: dict, records: dict,
                   client: RequestUtils = None) -> bool:
    """Observe saved tasks before any source/site/metadata lookup; never submit here."""
    if not self._pending_record(old):
        return False
    snapshot = old.get('media_snapshot') or old
    try:
        kind = normalize_media_type(snapshot.get('media_type'))
        season = snapshot.get('season')
        expected = snapshot.get('expected_episodes') or []
        media = MediaInfo(type=MediaType.MOVIE if kind == 'movie' else MediaType.TV,
                          tmdb_id=snapshot.get('tmdb_id'), douban_id=snapshot.get('douban_id'),
                          title=snapshot.get('title'), year=snapshot.get('year'), season=season,
                          seasons={season: expected} if season is not None else {})
    except (TypeError, ValueError):
        self._store(records, film_id, status='等待对账',
                    reason='旧记录缺少可核实媒体身份，保持去重等待人工核实')
        return True
    common = {key: old[key] for key in ('title', 'media_key', 'media_type', 'season',
                                        'tmdb_id', 'douban_id') if key in old}
    if kind == 'tv' and season is not None and not expected and not old.get('media_snapshot'):
        # Legacy records did not freeze season membership. Enrich only by their saved IDs;
        # an unavailable metadata service must not prevent task/STRM reconciliation.
        try:
            detail = MediaChain().recognize_media(mtype=media.type, tmdbid=media.tmdb_id,
                                                   doubanid=media.douban_id)
            if detail and normalize_media_type(detail.type) == kind and (
                    (media.tmdb_id and detail.tmdb_id == media.tmdb_id)
                    or (media.douban_id and detail.douban_id == media.douban_id)):
                media.seasons = detail.seasons
                if self._expected_episodes(media, season):
                    self._store(records, film_id, media_snapshot=self._media_snapshot(media, season))
        except Exception as exc:
            self._store(records, film_id, identity_error=type(exc).__name__)
    library_ready = old.get('library_ready') or old.get('status') == '待写回'
    if not library_ready and (media.tmdb_id or media.douban_id) and not (kind == 'tv' and season is None):
        try:
            library_ready = self._library_complete(media, season)
        except Exception as exc:
            self._store(records, film_id, library_error=type(exc).__name__)
    if library_ready:
        # Persist the completed library observation before crossing the API boundary.
        self._store(records, film_id, library_ready=True)
        if self._dry_run:
            self._store(records, film_id, status='待写回', reason='媒体库已存在；正式运行时写回')
        else:
            okay, reason = self._writeback_record(client, film_id, records[str(film_id)])
            self._store(records, film_id, status='已完成' if okay else '待写回', reason=reason)
        return True
    if old.get('route') in ('public_bt', '115_share'):
        return self._reconcile_115(film_id, snapshot['media_type'], common, old, records)
    download_hash = old.get('download_hash') or old.get('info_hash')
    present = self._task_present(download_hash) if download_hash else None
    if present and not old.get('download_hash'):
        self._store(records, film_id, download_hash=download_hash, task_state='SUBMITTED',
                    status='等待入库', reason='已按 info-hash 找回 M-Team 下载任务')
    else:
        self._store(records, film_id,
                    status='等待入库' if old.get('download_hash') else '提交结果待核实',
                    reason='已有下载任务，保持去重' if present else '任务状态未核实，保持去重')
    return True


def reconcile_115(self, film_id: int, media_type: str, common: dict,
                   old: dict, records: dict):
    """Never resubmit an ambiguous 115 task; cloud and STRM are separate states."""
    adapter = self._p115(old)
    route = old.get('route')
    if route == 'public_bt':
        info_hash = old.get('info_hash') or ''
        task = adapter.offline_task(info_hash) if info_hash else None
        if task is None:
            self._store(records, film_id, **common, status='等待对账',
                        reason='115 离线任务暂未出现，保持去重')
            return True
        state = int(task.get('status', -1))
        if state == 1:
            failed = list(old.get('failed_candidates') or [])
            if old.get('candidate_id') and old['candidate_id'] not in failed:
                failed.append(old['candidate_id'])
            failed_hashes = list(old.get('failed_hashes') or [])
            if info_hash and info_hash not in failed_hashes:
                failed_hashes.append(info_hash)
            self._store(records, film_id, **common, status='下载失败',
                        failed_candidates=failed, failed_hashes=failed_hashes,
                        task_state='FAILED',
                        reason='115 离线任务明确失败，重新选源')
            return False
        if state != 2:
            self._store(records, film_id, **common, status='115 下载中',
                        reason=f'115 离线状态 {state}')
            return True
        root_id = task.get('delete_file_id')
        if not root_id:
            self._store(records, film_id, **common, status='等待整理',
                        reason='115 任务已完成，云端文件 ID 尚不可查')
            return True
        root_ids = (int(root_id),)
    else:
        names = tuple(old.get('share_root_names') or [])
        items = adapter.cloud_items(media_type, names) if names else []
        if len(items) < len(names):
            self._store(records, film_id, **common, status='等待整理',
                        reason='115 分享已提交，等待目标目录出现全部文件')
            return True
        root_ids = tuple(int(item['id']) for item in items)
    if not old.get('strm_ready'):
        if self._dry_run:
            self._store(records, film_id, **common, status='预览',
                        reason='115 云端文件已存在；正式运行时生成 STRM')
            return True
        created = adapter.ensure_strm(media_type, root_ids)
        if not created:
            self._store(records, film_id, **common, status='等待整理',
                        reason='云端文件已存在，STRM 尚未生成')
            return True
        self._store(records, film_id, **common, cloud_root_ids=list(root_ids),
                    strm_ready=True, status='等待入库',
                    reason='115 文件已入目标目录并生成 STRM，等待媒体库确认')
    else:
        self._store(records, film_id, **common, status='等待入库',
                    reason='115 文件已整理，等待媒体库确认')
    return True
