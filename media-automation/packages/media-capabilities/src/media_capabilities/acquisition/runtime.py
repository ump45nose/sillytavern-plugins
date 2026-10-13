"""MoviePilot acquisition runtime shared by independent consumers."""
from dataclasses import dataclass
import math
from threading import Lock, RLock

from ..store import PluginTaskStore
from .media_types import normalize_media_type
from .moviepilot_host import MTeamAdapter, Mini4KAdapter, MoviePilotDownloadAdapter, MoviePilotIdentity
from .p115_task_adapter import P115TaskAdapter
from .policies import ProfileSettings
from .public_index import IndexStatus, LinuxBrowserTransport, Mini4KIndexer
from .service import AcquisitionService, SubmissionRegistry


class HostUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class AcquisitionSettings:
    enabled: bool = False
    site_id: int = 1
    mini4k_base_url: str = 'https://mini4k.io'
    public_site_preview: bool = False
    public_only: bool = False
    p115_route_enabled: bool = True
    share_115_enabled: bool = False
    near_size_ratio: float = .10
    balanced_movie_gib: float = 35
    balanced_episode_gib: float = 8
    p115_movie_path: str = '/Media/Movie'
    p115_tv_path: str = '/Media/TV_Show'
    local_strm_root: str = '/Media/115_strm'
    # Keep existing login/session files; names are historical, not plugin dependencies.
    browser_profile_dir: str = '/config/filmwatchlist-mini4k-cloak-browser'

    @classmethod
    def parse(cls, data):
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        for key in ('enabled', 'public_site_preview', 'public_only', 'p115_route_enabled', 'share_115_enabled'):
            if key in values:
                if not isinstance(values[key], bool):
                    raise ValueError(key + ' 必须是布尔值')
        if 'site_id' in values:
            values['site_id'] = int(values['site_id'])
            if values['site_id'] < 1:
                raise ValueError('站点 ID 必须是正整数')
        for key, minimum in (('near_size_ratio', 0), ('balanced_movie_gib', 1), ('balanced_episode_gib', .1)):
            if key in values:
                values[key] = float(values[key])
                if not math.isfinite(values[key]) or values[key] < minimum:
                    raise ValueError(key + ' 无效')
        if values.get('near_size_ratio', .1) > .5:
            raise ValueError('near_size_ratio 不能超过 0.5')
        settings = cls(**values)
        Mini4KIndexer(base_url=settings.mini4k_base_url)
        P115TaskAdapter(settings.p115_movie_path, settings.p115_tv_path, settings.local_strm_root)
        return settings


class HostResources:
    def __init__(self, plugin):
        self.registry = SubmissionRegistry(PluginTaskStore(plugin, 'acquisition_v1'))
        self.navigation_lock = Lock()
        self.lock = RLock()
        self.runtime = None


_resources = {}
_resources_lock = RLock()


def host_resources(plugin):
    """Keep submission and browser locks across plugin object/config reloads."""
    with _resources_lock:
        if 'MediaCapabilities' not in _resources:
            _resources['MediaCapabilities'] = HostResources(plugin)
        resources = _resources['MediaCapabilities']
        with resources.registry.lock:
            resources.registry.store = PluginTaskStore(plugin, 'acquisition_v1')
        return resources


class AcquisitionRuntime:
    def __init__(self, settings, resources):
        self.settings, self.registry = settings, resources.registry
        self.navigation_lock = resources.navigation_lock
        self.lock = RLock()
        self.closed = False
        self._indexer = self._service = None

    def ensure_active(self):
        if self.closed or not self.settings.enabled:
            raise HostUnavailable('公共获取宿主未启用或正在重载，暂停新提交')

    def indexer(self):
        with self.lock:
            if self.closed:
                raise HostUnavailable('公共获取宿主正在重载')
            if self._indexer is None:
                browser = LinuxBrowserTransport(self.settings.browser_profile_dir,
                                                navigation_lock=self.navigation_lock)
                self._indexer = Mini4KIndexer(base_url=self.settings.mini4k_base_url,
                                              browser=browser)
            return self._indexer

    def p115(self, record=None, registered=True):
        movie_path, tv_path = self.settings.p115_movie_path, self.settings.p115_tv_path
        if record and record.get('target_path'):
            if normalize_media_type(record.get('media_type')) == 'movie':
                movie_path = record['target_path']
            else:
                tv_path = record['target_path']
        adapter = P115TaskAdapter(movie_path, tv_path,
                                 (record or {}).get('local_strm_root') or self.settings.local_strm_root)
        if registered:
            adapter.submission_registry = self.registry
            adapter.submission_guard = self.ensure_active
        return adapter

    def raw_p115(self, record=None):
        return self.p115(record, registered=False)

    def execution(self, readonly=False):
        if not readonly:
            self.ensure_active()
        with self.lock:
            if self.closed:
                raise HostUnavailable('公共获取宿主正在重载')
            if self._service is None:
                identities = MoviePilotIdentity()
                self._service = AcquisitionService(identities,
                    [MTeamAdapter(self.settings, identities),
                     Mini4KAdapter(self.settings, self.indexer, self.raw_p115)],
                    MoviePilotDownloadAdapter(self.raw_p115, self.ensure_active), self.registry,
                    ProfileSettings(self.settings.near_size_ratio,
                        self.settings.balanced_movie_gib, self.settings.balanced_episode_gib),
                    public_only=self.settings.public_only)
            return self._service

    def submit_pt(self, task_id, info_hash, context, content, source='MediaAcquisition'):
        from app.chain.download import DownloadChain
        def submit():
            handle, _ = DownloadChain().download_single(context, torrent_content=content,
                source=source, username=source, return_detail=True)
            return {'status': 'submitted' if handle else 'pending', 'download_hash': handle or ''}
        return self.registry.submit(task_id, info_hash, {'route': 'pt', 'info_hash': info_hash},
                                    submit, authorize=self.ensure_automatic_pt_allowed)

    def ensure_automatic_pt_allowed(self):
        self.ensure_active()
        if self.settings.public_only:
            raise HostUnavailable('仅公网自动选源已开启，暂停新的 PT 自动提交')

    def search_public(self, query):
        items, cursor = {}, None
        for _ in range(12):
            page = self.indexer().search(query, cursor)
            if page.status not in (IndexStatus.OK, IndexStatus.NO_RESULTS):
                return page.status, list(items.values()), page.reason
            for candidate in page.candidates:
                items[candidate.candidate_id] = candidate
            cursor = page.next_cursor
            if not cursor:
                return IndexStatus.OK if items else IndexStatus.NO_RESULTS, list(items.values()), ''
        return IndexStatus.PARSE_CHANGED, list(items.values()), '搜索超过分页上限'

    def preview_torrents(self, site, keyword, mtype=None, page=0):
        import re
        from collections import UserList
        from app.core.context import TorrentInfo
        from app.schemas.types import MediaType
        from .public_index import MediaQuery
        if not self.settings.public_site_preview or site.get('id') not in (
                'MediaCapabilities-Mini4K', 'FilmWatchlist-Mini4K'):
            return []
        if page:
            return UserList()
        year = re.search(r'(?:19|20)\d{2}', keyword or '')
        title = (keyword or '').replace(year[0], '').strip() if year else keyword
        kind = ('movie' if mtype == MediaType.MOVIE else 'tv') if mtype else None
        status, candidates, _ = self.search_public(MediaQuery(title=title or keyword,
            year=int(year[0]) if year else None, media_type=kind))
        if status not in (IndexStatus.OK, IndexStatus.NO_RESULTS):
            return UserList()
        return UserList(TorrentInfo(site_name='Mini4K（搜索预览）', title=c.title,
            description='仅供预览，请通过独立入口核验并下载', enclosure='',
            page_url=c.resource_page_url, size=c.size_bytes or 0,
            category=MediaType.MOVIE.value if c.media_type == 'movie' else MediaType.TV.value) for c in candidates)

    def import_legacy_records(self, records):
        from .migration import migrate_registry
        migrate_registry(self.registry, {}, records)

    def close(self):
        # An intent already reserved remains owned by this registry during reload.
        with self.registry.lock:
            self.closed = True
        with self.lock:
            if self._service:
                self._service.close()


def get_runtime(readonly=False):
    from app.core.plugin import PluginManager
    getter = PluginManager().get_plugin_attr('MediaCapabilities', 'get_runtime')
    if not callable(getter):
        raise HostUnavailable('请安装并启用 MediaCapabilities 公共宿主插件')
    return getter(readonly=readonly)


def guarded(function, *args):
    try:
        return function(*args)
    except HostUnavailable as exc:
        return {'status': 'unavailable', 'reason': str(exc)}
    except (ValueError, TypeError) as exc:
        return {'status': 'invalid_request', 'reason': str(exc)}
    except Exception:
        return {'status': 'unavailable', 'reason': '宿主能力不可用，请检查服务端日志与配置'}
