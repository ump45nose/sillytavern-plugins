"""Independent MoviePilot host for the shared acquisition package."""
from dataclasses import asdict

from app.plugins import _PluginBase
from app.log import logger


class MediaCapabilities(_PluginBase):
    plugin_name = '公共媒体获取能力'
    plugin_desc = '为片单、独立查询网页和下载 MCP 提供共享的搜索、核验与下载宿主'
    plugin_icon = 'Moviepilot_A.png'
    plugin_version = '0.1.1'
    plugin_author = 'yuwk'
    author_url = ''
    plugin_config_prefix = 'mediacapabilities_'
    plugin_order = 59
    auth_level = 1

    def __init__(self):
        super().__init__()
        self.config, self.error, self.runtime = {}, '', None

    def init_plugin(self, config=None):
        self.stop_service()
        self.error = ''
        try:
            from media_capabilities.acquisition.runtime import AcquisitionSettings, AcquisitionRuntime, host_resources
            from media_capabilities.acquisition.migration import settings_from_legacy, migrate_registry
            resources = host_resources(self)
            with resources.lock:
                if resources.runtime:
                    resources.runtime.close()
                current = dict(config if config is not None else self.get_config() or {})
                migration = self.get_data('migration_v1') or {}
                if not migration.get('complete'):
                    current = settings_from_legacy(current, self.get_config('FilmWatchlist') or {})
                settings = AcquisitionSettings.parse(current)
                self.config = asdict(settings)
                if not migration.get('complete'):
                    # Native storage access works even when FilmWatchlist is not loaded.
                    migrate_registry(resources.registry,
                        self.get_data('acquisition_v1', plugin_id='FilmWatchlist') or {},
                        self.get_data('records', plugin_id='FilmWatchlist') or {})
                    if self.update_config(self.config) is False:
                        raise RuntimeError('公共宿主配置保存失败')
                    self.save_data('migration_v1', {'complete': True})
                self.runtime = AcquisitionRuntime(settings, resources)
                resources.runtime = self.runtime
            if self.get_state() and settings.public_site_preview:
                from app.helper.sites import SitesHelper
                domain = 'mini4k.mediacapabilities.preview'
                SitesHelper().add_indexer(domain, {'id': 'MediaCapabilities-Mini4K',
                    'name': 'Mini4K（搜索预览）', 'url': settings.mini4k_base_url,
                    'domain': domain, 'public': True, 'proxy': False})
        except Exception as exc:
            if self.runtime:
                self.runtime.close()
            self.runtime = None
            self.error = '请安装 media-capabilities[acquisition] 0.3.1' if isinstance(exc, ModuleNotFoundError) \
                else str(exc) if isinstance(exc, ValueError) else '公共获取宿主初始化失败，请检查配置和持久化存储'
            logger.warning(self.error)

    def get_runtime(self, readonly=False):
        from media_capabilities.acquisition.runtime import HostUnavailable
        if not self.runtime or self.error:
            raise HostUnavailable(self.error or '公共获取宿主尚未初始化')
        if not readonly:
            self.runtime.ensure_active()
        return self.runtime

    def get_state(self):
        return bool(self.runtime and not self.error and not self.runtime.closed and self.config.get('enabled'))

    def get_service(self):
        return []

    @staticmethod
    def get_command():
        return []

    def get_api(self):
        return [{'path': path, 'endpoint': endpoint, 'methods': methods, 'auth': 'bear', 'summary': summary}
            for path, endpoint, methods, summary in [
                ('/acquisition_search', self.acquisition_search, ['POST'], '开始聚合资源查询'),
                ('/acquisition_search_status', self.acquisition_search_status, ['GET'], '读取逐站查询结果'),
                ('/acquisition_more', self.acquisition_more, ['POST'], '查询下一页资源'),
                ('/acquisition_download', self.acquisition_download, ['POST'], '原子选源与下载提交'),
                ('/acquisition_status', self.acquisition_status, ['GET'], '读取下载回执与进度'),
            ]]

    def acquisition_search(self, payload: dict) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(lambda: self.get_runtime().execution().start_search(payload))

    def acquisition_search_status(self, session_id: str) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(lambda: self.get_runtime(readonly=True).execution(readonly=True).search_status(session_id))

    def acquisition_more(self, payload: dict) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(lambda: self.get_runtime().execution().more(payload['session_id'], payload['source_id']))

    def acquisition_download(self, payload: dict, wait_timeout: float = 120) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(lambda: self.get_runtime().execution().download(payload, wait_timeout))

    def acquisition_status(self, task_id: str) -> dict:
        from media_capabilities.acquisition.runtime import guarded
        return guarded(lambda: self.get_runtime(readonly=True).execution(readonly=True).status(task_id))

    def get_module(self):
        return {'search_torrents': self.search_public_torrents, 'async_search_torrents': self.search_public_torrents} \
            if self.get_state() and self.config.get('public_site_preview') else {}

    def search_public_torrents(self, site: dict, keyword: str, mtype=None, page: int = 0):
        if not self.get_state() or not self.config.get('public_site_preview'):
            return []
        return self.get_runtime().preview_torrents(site, keyword, mtype, page)

    def get_form(self):
        fields = [
            ('VSwitch', 'enabled', '启用公共获取宿主'),
            ('VSwitch', 'public_site_preview', 'MoviePilot 聚合查询中显示 Mini4K 预览'),
            ('VSwitch', 'public_only', '自动下载仅公网资源（手动指定 PT 不受限制）'),
            ('VSwitch', 'p115_route_enabled', '公网 BT 下载到 115（默认开启）'),
            ('VSwitch', 'share_115_enabled', '允许 115 分享转存'),
            ('VTextField', 'site_id', 'M-Team 站点 ID'),
            ('VTextField', 'mini4k_base_url', 'Mini4K 索引域名'),
            ('VTextField', 'near_size_ratio', '质量模式同档体积相近阈值'),
            ('VTextField', 'balanced_movie_gib', '均衡模式电影体积上限 GiB'),
            ('VTextField', 'balanced_episode_gib', '均衡模式平均每集上限 GiB'),
            ('VTextField', 'p115_movie_path', '115 电影目录'),
            ('VTextField', 'p115_tv_path', '115 剧集目录'),
            ('VTextField', 'local_strm_root', '旧片单恢复使用的 STRM 根目录'),
            ('VTextField', 'browser_profile_dir', 'Mini4K 浏览器会话目录'),
            ('VTextField', 'relay_device_id_path', 'Browser Relay Device ID 文件'),
            ('VTextField', 'relay_tab_id_path', 'Browser Relay Tab ID 文件'),
            ('VTextField', 'relay_origin_path', 'Browser Relay 已登录域名文件'),
        ]
        content = [{'component': 'VRow', 'content': [{'component': 'VCol', 'props': {'cols': 12, 'md': 6},
            'content': [{'component': component, 'props': {'model': key, 'label': label}}]}]}
            for component, key, label in fields]
        try:
            from media_capabilities.acquisition.runtime import AcquisitionSettings
            defaults = asdict(AcquisitionSettings())
        except ModuleNotFoundError:
            defaults = {'enabled': False}
        return [{'component': 'VForm', 'content': content}], defaults

    def get_page(self):
        return [{'component': 'VAlert', 'props': {'type': 'warning' if self.error else 'info',
            'text': self.error or '公共能力已独立承载；首次迁移保留原片单数据，下载开关由此插件统一管理。'}}]

    def stop_service(self):
        if self.runtime:
            self.runtime.close()
