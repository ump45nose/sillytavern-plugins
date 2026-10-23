"""把 Favsync 片单接入 MoviePilot V2 的 M-Team 搜索与下载链路。"""

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from time import sleep
from typing import Any

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.chain.download import DownloadChain
from app.chain.media import MediaChain
from app.chain.search import SearchChain
from app.core.config import settings
from app.db.downloadhistory_oper import DownloadHistoryOper
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import MediaType
from app.utils.http import RequestUtils

from app.plugins.filmwatchlist.selection import normalize_title
from app.plugins.filmwatchlist.public_index import IndexStatus, MediaQuery
from app.plugins.filmwatchlist.p115_task_adapter import P115TaskAdapter
from app.plugins.filmwatchlist.media_types import normalize_media_type
from app.plugins.filmwatchlist import observe, state, workflow


class FilmWatchlist(_PluginBase):
    """同步片单，挑选可播放的最高质量资源并跟踪入库状态。"""

    plugin_name = "片单自动收藏"
    plugin_desc = "从 Favsync 片单比较公网和 M-Team 资源，按来源下载并在入库后回写。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.4.4"
    plugin_author = "yuwk"
    author_url = ""
    plugin_config_prefix = "filmwatchlist_"
    plugin_order = 60
    auth_level = 1

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._dry_run = True
        self._api_url = "http://192.168.31.201:18082"
        self._token_path = "/config/filmwatchlist.token"
        self._interval_minutes = 360
        self._identity_hints = {}
        self._public_selection_enabled = False
        self._scheduler = None
        self._lock = Lock()
        self._legacy_registered = False

    def init_plugin(self, config: dict = None):
        """读取配置，并为一次性运行建立可清理的后台任务。"""
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._dry_run = bool(config.get("dry_run", True))
        self._api_url = str(config.get("api_url") or self._api_url).rstrip("/")
        self._token_path = str(config.get("token_path") or self._token_path)
        self._interval_minutes = max(30, int(config.get("interval_minutes") or 360))
        self._public_selection_enabled = bool(config.get('public_selection_enabled', False))
        try:
            hints = json.loads(config.get("identity_hints") or "{}")
            self._identity_hints = hints if isinstance(hints, dict) else {}
        except (TypeError, ValueError):
            self._identity_hints = {}
        if self._enabled and config.get("run_now"):
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                self.run_once, trigger="date",
                run_date=datetime.now(pytz.timezone(settings.TZ)) + timedelta(seconds=3),
            )
            self._scheduler.start()
            self.update_config({**config, "run_now": False})

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> list[dict[str, Any]]:
        """当前不注册远程聊天命令。"""
        return []

    def get_api(self) -> list[dict[str, Any]]:
        """提供受保护的公网搜索及指定候选链接解析接口。"""
        return [
            {"path": "/public_health", "endpoint": self.public_health_api,
             "methods": ["GET"], "auth": "bear", "summary": "公网索引健康状态"},
            {"path": "/public_search", "endpoint": self.public_search_api,
             "methods": ["GET"], "auth": "bear", "summary": "预览公网候选"},
            {"path": "/public_resolve", "endpoint": self.public_resolve_api,
             "methods": ["GET"], "auth": "bear", "summary": "解析公网候选链接"},
        ]

    def _capabilities(self):
        from media_capabilities.acquisition.runtime import get_runtime
        runtime = get_runtime(readonly=True)
        if not self._legacy_registered:
            runtime.import_legacy_records(self.get_data('records') or {})
            self._legacy_registered = True
        return runtime

    @property
    def _site_id(self):
        return self._capabilities().settings.site_id

    @property
    def _near_size_ratio(self):
        return self._capabilities().settings.near_size_ratio

    @property
    def _public_only(self):
        return self._capabilities().settings.public_only

    @property
    def _p115_route_enabled(self):
        return self._capabilities().settings.p115_route_enabled

    @property
    def _share_115_enabled(self):
        return self._capabilities().settings.share_115_enabled

    def get_module(self) -> dict[str, Any]:
        return {}

    def _indexer(self):
        return self._capabilities().indexer()

    def _search_public(self, query: MediaQuery) -> tuple[IndexStatus, list, str]:
        return self._capabilities().search_public(query)

    def public_health_api(self) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(self._public_health_result)

    def _public_health_result(self) -> dict:
        result = self._indexer().health()
        return {"status": result.status.value, "reason": result.reason,
                "page_status": result.page_status.value if result.page_status else None,
                "resolve_status": result.resolve_status.value if result.resolve_status else 'NOT_CHECKED'}

    def public_search_api(self, title: str, year: int = None, country: str = None,
                          media_type: str = None, aliases: str = "",
                          tmdb_id: int = None, imdb_id: str = None, season: int = None) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(self._public_search_result, title, year, country, media_type, aliases, tmdb_id, imdb_id, season)

    def _public_search_result(self, title, year, country, media_type, aliases, tmdb_id, imdb_id, season):
        """预览接口只返回候选，不解析所有链接或提交任务。"""
        query = MediaQuery(title=title, year=year, country=country, media_type=media_type,
                           aliases=tuple(x.strip() for x in aliases.split(",") if x.strip()),
                           tmdb_id=tmdb_id, imdb_id=imdb_id, season=season)
        status, items, reason = self._search_public(query)
        return {"status": status.value, "candidates": [asdict(item) for item in items],
                "reason": reason}

    def public_resolve_api(self, candidate_id: str) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(self._public_resolve_result, candidate_id)

    def _public_resolve_result(self, candidate_id):
        """种子字节仅供插件内部后续链路使用，不写入 API 响应。"""
        result = self._indexer().resolve(candidate_id)
        links = [{key: value for key, value in asdict(link).items() if key != "torrent_bytes"}
                 for link in result.links]
        return {"status": result.status.value, "candidate_id": candidate_id,
                "links": links, "reason": result.reason}

    def search_public_torrents(self, site: dict, keyword: str, mtype=None, page: int = 0):
        return self._capabilities().preview_torrents(site, keyword, mtype, page)

    def get_service(self) -> list[dict[str, Any]]:
        """注册片单定时扫描；同一时刻仅有一次运行。"""
        if not self._enabled:
            return []
        return [{"id": "FilmWatchlist", "name": "片单自动收藏扫描", "trigger": "interval",
                 "func": self.run_once, "kwargs": {"minutes": self._interval_minutes}}]

    def get_form(self) -> tuple[list[dict], dict]:
        """提供预览开关、片单连接和调度参数。"""
        fields = [
            ("VSwitch", "enabled", "启用片单扫描"),
            ("VSwitch", "dry_run", "片单仅预览，不提交下载或回写"),
            ("VSwitch", "public_selection_enabled", "启用公网与 PT 统一选源"),
            ("VSwitch", "run_now", "保存后立即运行一次"),
            ("VTextField", "api_url", "片单 API 地址"),
            ("VTextField", "token_path", "令牌文件路径"),
            ("VTextField", "interval_minutes", "扫描间隔（分钟，最少 30）"),
            ("VTextarea", "identity_hints", "已核实媒体 ID（按片单 ID 填 JSON）"),
        ]
        content = [{"component": "VRow", "content": [{"component": "VCol",
                   "props": {"cols": 12, "md": 6}, "content": [{"component": component,
                   "props": {"model": model, "label": label}}]}]}
                   for component, model, label in fields]
        return [{"component": "VForm", "content": content}], {
            "enabled": False, "dry_run": True, "run_now": False,
            "public_selection_enabled": False, "api_url": "http://192.168.31.201:18082",
            "token_path": "/config/filmwatchlist.token", "interval_minutes": 360, "identity_hints": "{}",
        }

    def get_page(self) -> list[dict]:
        """显示每条记录的候选、排除原因及下载状态。"""
        records = self.get_data("records") or {}
        rows = sorted(({
            **row,
            "rejected_text": "；".join(row.get("rejected") or []),
        } for row in records.values()), key=lambda row: int(row.get("film_id") or 0))
        run = self.get_data("last_run") or {}
        summary = (f"模式：{'预览' if self._dry_run else '正式'}；"
                   f"上次运行：{run.get('time', '尚未运行')}；"
                   f"结果：{run.get('summary', '暂无')}")
        return [
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": summary}},
            {"component": "VDataTableVirtual", "props": {
                "headers": [
                    {"title": "片单ID", "key": "film_id"},
                    {"title": "标题", "key": "title"},
                    {"title": "状态", "key": "status"},
                    {"title": "所选资源", "key": "torrent_title"},
                    {"title": "来源", "key": "route"},
                    {"title": "115 目标目录", "key": "target_path"},
                    {"title": "视频字节", "key": "video_bytes"},
                    {"title": "说明", "key": "reason"},
                    {"title": "排除候选", "key": "rejected_text"},
                ],
                "items": rows, "height": "34rem", "density": "compact", "fixed-header": True,
            }},
        ]

    def stop_service(self):
        """停止片单调度，不影响公共宿主及其他消费者。"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    def _client(self) -> RequestUtils:
        """从独立只读文件装载令牌，不向日志和插件数据写入。"""
        token = Path(self._token_path).read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("片单令牌文件为空")
        return RequestUtils(headers={"Authorization": f"Bearer {token}",
                                     "Accept": "application/json"}, timeout=12)

    def _films(self, client: RequestUtils) -> list[dict]:
        """分页读取全部未下载片单，拒绝不完整或异常响应。"""
        films = []
        offset = 0
        while True:
            response = client.get_res(
                f"{self._api_url}/v1/films",
                params={"offset": offset, "limit": 200, "downloaded": "false"},
            )
            if response is None or response.status_code != 200:
                raise RuntimeError(f"片单读取失败：HTTP {response.status_code if response is not None else '无响应'}")
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise ValueError("片单响应缺少 items")
            films.extend(item for item in items if item.get("active") is True)
            offset += len(items)
            if not items or offset >= int(payload.get("total", offset)):
                return films

    @staticmethod
    def _country_matches(media, wanted: str) -> bool:
        """比较详情中的出品国家，兼容常见中文、英文和 ISO 写法。"""
        aliases = {
            "fr": {"fr", "france", "法国"},
            "us": {"us", "usa", "unitedstates", "unitedstatesofamerica", "美国"},
        }
        target = normalize_title(wanted)
        wanted_keys = next((values for values in aliases.values() if target in values), {target})
        actual = set()
        countries = (getattr(media, "production_countries", None) or []) + \
                    (getattr(media, "origin_country", None) or [])
        for country in countries:
            values = country.values() if isinstance(country, dict) else [country]
            actual.update(normalize_title(str(value)) for value in values if value)
        return bool(wanted_keys & actual)

    @staticmethod
    def _identify(item: dict, hint: dict | None = None):
        """Verify the series identity separately from the requested season's release."""
        from media_capabilities.acquisition.seasons import split_season_title
        title = str(item.get("title") or "").strip()
        if not title:
            return None, None, "片名为空"
        try:
            base_title, title_season = split_season_title(title)
            season_value = item.get('season')
            if season_value is not None and (type(season_value) is not int or not 1 <= season_value <= 999):
                raise ValueError('片单季数无效')
            if season_value and title_season and season_value != title_season:
                raise ValueError('片单季数与标题冲突')
            if item.get('season_error'):
                raise ValueError(str(item['season_error']))
            requested_season = season_value or title_season
        except ValueError as exc:
            return None, None, str(exc)
        year = item.get("release_year")
        chain = MediaChain()
        wanted_type = normalize_media_type(item['media_type']) if item.get('media_type') else None
        if requested_season:
            if wanted_type == 'movie':
                return None, None, '电影片单不能指定电视剧季数'
            wanted_type = 'tv'

        def match(media):
            if not media:
                return False, None
            kind = normalize_media_type(media.type)
            if wanted_type and wanted_type != kind:
                return False, None
            names = [media.title, getattr(media, 'original_title', None), *(getattr(media, 'names', None) or [])]
            keys = set()
            for name in names:
                if name:
                    try:
                        keys.add(normalize_title(split_season_title(name)[0] if kind == 'tv' else name))
                    except ValueError:
                        continue
            if normalize_title(base_title if kind == 'tv' else title) not in keys:
                return False, None
            if item.get('country') and not FilmWatchlist._country_matches(media, item['country']):
                return False, None
            release = item.get('release_date')
            if kind != 'tv':
                actual = getattr(media, 'release_date', None) or getattr(media, 'first_air_date', None)
                return (not year or str(media.year or '') == str(year)) and (not release or actual == release), None
            seasons = getattr(media, 'seasons', None) or {}
            info = getattr(media, 'season_info', None) or []
            dates = {int(s['season_number']): s.get('air_date') for s in info if s.get('season_number') is not None}
            years = {int(k): str(v) for k, v in (getattr(media, 'season_years', None) or {}).items()}
            # Douban's separate season entries have a season-specific release date.
            _, named_season = split_season_title(media.title)
            native_season = named_season or (getattr(media, 'season', None) if not media.tmdb_id else None)
            if native_season:
                actual = getattr(media, 'release_date', None) or getattr(media, 'first_air_date', None)
                dates.setdefault(native_season, actual)
                years.setdefault(native_season, str(media.year or ''))
            for number, date in dates.items():
                if date:
                    years[number] = date[:4]
            target = requested_season or named_season
            if target is None:
                matches = [int(s) for s, episodes in seasons.items() if int(s) > 0 and episodes
                           and (not year or years.get(int(s)) == str(year))
                           and (not release or dates.get(int(s)) == release)]
                if len(matches) == 1:
                    target = matches[0]
                elif not dates and not years and (not year or str(media.year or '') == str(year)):
                    target = 1  # Legacy single-season metadata; never infer a later season.
                else:
                    return False, None
            if not (seasons.get(target) or seasons.get(str(target))):
                return False, None
            actual_date = dates.get(target)
            actual_year = years.get(target)
            if target == 1:
                actual_date = actual_date or getattr(media, 'first_air_date', None) or getattr(media, 'release_date', None)
                actual_year = actual_year or str(media.year or '')
            if (year and actual_year != str(year)) or (release and actual_date != release):
                return False, None
            return True, target

        if isinstance(hint, dict) and (hint.get('tmdb_id') or hint.get('douban_id')):
            try:
                kind = normalize_media_type(hint.get('media_type') or wanted_type)
                hinted = chain.recognize_media(mtype=MediaType.TV if kind == 'tv' else MediaType.MOVIE,
                                              tmdbid=hint.get('tmdb_id'), doubanid=hint.get('douban_id'))
                okay, season = match(hinted)
                if okay:
                    hinted.season = season
                    return hinted, season, ''
            except (TypeError, ValueError):
                pass
        # A season's year must not be passed as the series' first-air year.
        query = base_title if wanted_type == 'tv' else f'{title} ({year})' if year else title
        retry = bool(year and str(year).isdigit() and int(year) < datetime.now().year)
        candidates = []
        for attempt in range(3 if retry else 1):
            if attempt:
                sleep(2 * attempt)
            _, candidates = chain.search(query)
            if candidates:
                break
        if not candidates and year and query != base_title:
            _, candidates = chain.search(base_title)
        if not candidates:
            return None, None, 'MoviePilot 元数据搜索暂未返回结果'
        verified = []
        for candidate in candidates:
            try:
                kind = normalize_media_type(candidate.type)
                if wanted_type and kind != wanted_type:
                    continue
                media = chain.recognize_media(mtype=MediaType.TV if kind == 'tv' else MediaType.MOVIE,
                                              tmdbid=candidate.tmdb_id, doubanid=candidate.douban_id,
                                              bangumiid=getattr(candidate, 'bangumi_id', None))
                okay, season = match(media)
                if okay:
                    verified.append((media, season))
            except (TypeError, ValueError):
                continue
        # TMDB models the full series; Douban may also return separate season entries.
        tv_tmdb = [(m, s) for m, s in verified if normalize_media_type(m.type) == 'tv' and m.tmdb_id]
        if tv_tmdb:
            verified = tv_tmdb
        distinct = {(normalize_media_type(m.type), m.tmdb_id or m.douban_id, s) for m, s in verified}
        if len(distinct) != 1:
            return None, None, '媒体识别不唯一或名称/目标季上映时间/国家不匹配'
        media, season = verified[0]
        media.season = season
        return media, season, ''

    @staticmethod
    def _expected_episodes(media, season: int | None) -> set[int] | None:
        return state.expected_episodes(media, season)

    @staticmethod
    def _library_complete(media, season: int | None) -> bool:
        """只以媒体服务器库中的目标电影或完整剧集季为完成依据。"""
        existing = MediaChain().media_exists(mediainfo=media)
        if not existing:
            return False
        if season is None:
            return True
        expected = FilmWatchlist._expected_episodes(media, season)
        actual = (existing.seasons or {}).get(season) or (existing.seasons or {}).get(str(season)) or []
        return bool(expected) and expected.issubset({int(episode) for episode in actual})

    @staticmethod
    def _other_download(media, season: int | None) -> bool:
        """尊重已有 MoviePilot 下载历史，避免与其他任务重复下载。"""
        histories = DownloadHistoryOper().get_by_mediaid(media.tmdb_id, media.douban_id) or []
        if season is None:
            return bool(histories)
        return any(not history.seasons or f"S{season:02d}" in history.seasons.upper()
                   for history in histories)

    @staticmethod
    def _task_present(download_hash: str) -> bool | None:
        """向现有下载器核对已记录任务；无法查询时保持保守等待。"""
        try:
            tasks = DownloadChain().list_torrents(hashs=[download_hash], include_all_tags=True)
            return bool(tasks) if tasks is not None else None
        except Exception as exc:
            logger.warning(f"片单下载任务核对失败：{type(exc).__name__}")
            return None

    def _mark_downloaded(self, client: RequestUtils, film_id: int) -> tuple[bool, str]:
        """媒体入库后回写片单；失败时下轮继续重试。"""
        try:
            client = client or self._client()
            response = client.request("PATCH", f"{self._api_url}/v1/films/{film_id}/downloaded",
                                      json={"downloaded": True})
        except Exception as exc:
            return False, f'片单写回失败：{type(exc).__name__}'
        if response is None or response.status_code != 200:
            return False, f"片单写回失败：HTTP {response.status_code if response is not None else '无响应'}"
        return True, "已入库并写回片单"

    @staticmethod
    def _source_snapshot(item: dict) -> dict:
        return state.source_snapshot(item)

    def _writeback_record(self, client: RequestUtils, film_id: int, record: dict) -> tuple[bool, str]:
        return observe.writeback_record(self, client, film_id, record)

    def _store(self, records: dict, film_id: int, **values):
        return state.store(self, records, film_id, **values)

    def _p115(self, record: dict | None = None) -> P115TaskAdapter:
        return self._capabilities().p115(record)

    @staticmethod
    def _pending_record(record: dict) -> bool:
        return state.pending_record(record)

    @staticmethod
    def _media_snapshot(media, season: int | None) -> dict:
        return state.media_snapshot(media, season)

    def _resume_record(self, film_id: int, old: dict, records: dict,
                       client: RequestUtils = None) -> bool:
        return observe.resume_record(self, film_id, old, records, client)

    def _submit_pt(self, film_id: int, context, content: bytes, decision: dict, records: dict):
        return workflow.submit_pt(self, film_id, context, content, decision, records)

    def _reconcile_115(self, film_id: int, media_type: str, common: dict,
                       old: dict, records: dict):
        return observe.reconcile_115(self, film_id, media_type, common, old, records)

    def _process_unified(self, film_id: int, item: dict, media, media_type: str,
                         expected: set[int] | None, common: dict, records: dict):
        return workflow.process_unified(self, film_id, item, media, media_type, expected, common, records)

    def _process_one(self, item: dict, client: RequestUtils, records: dict):
        return workflow.process_one(self, item, client, records)

    def run_once(self):
        """完整扫描一次；运行锁避免定时任务和手动任务重叠。"""
        if not self._enabled or not self._lock.acquire(blocking=False):
            return
        try:
            records = self.get_data("records") or {}
            recovered = set()
            failed = 0
            for key, old in list(records.items()):
                if not self._pending_record(old):
                    continue
                film_id = int(old.get('film_id') or key)
                try:
                    if self._resume_record(film_id, old, records):
                        recovered.add(str(film_id))
                except Exception as exc:
                    recovered.add(str(film_id))
                    failed += 1
                    self._store(records, film_id, status='等待对账', reason=type(exc).__name__)
                    logger.warning(f'片单 {film_id} 恢复暂不可用：{type(exc).__name__}')
            films = []
            scan_error = ''
            try:
                site = SiteOper().get(self._site_id)
                if not site or not site.is_active or not (
                        "m-team" in (site.domain or "").lower() or site.name == "馒头"):
                    raise ValueError("所选站点不是已启用的 M-Team")
                client = self._client()
                films = self._films(client)
            except Exception as exc:
                scan_error = f'；新片单扫描暂停：{type(exc).__name__}'
            for item in films:
                if str(item.get('id')) in recovered:
                    continue
                try:
                    self._process_one(item, client, records)
                except Exception as exc:
                    failed += 1
                    film_id = int(item.get("id") or 0)
                    self._store(records, film_id, title=item.get("title") or "",
                                status="失败", reason=type(exc).__name__)
                    logger.error(f"片单 {film_id} 扫描失败：{type(exc).__name__}")
            summary = f"恢复 {len(recovered)} 条，扫描 {len(films)} 条，失败 {failed} 条{scan_error}"
            self.save_data("last_run", {"time": datetime.now().isoformat(timespec="seconds"),
                                        "summary": summary})
            logger.info(f"片单自动收藏：{summary}")
        except Exception as exc:
            self.save_data("last_run", {"time": datetime.now().isoformat(timespec="seconds"),
                                        "summary": f"运行失败：{type(exc).__name__}"})
            logger.error(f"片单自动收藏运行失败：{type(exc).__name__}")
        finally:
            self._lock.release()
