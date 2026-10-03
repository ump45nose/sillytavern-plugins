"""Small offline MoviePilot host contract; no application/network service is started."""
import importlib.util
import logging
import sys
import types
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from unittest.mock import Mock


def module(name, **attrs):
    result = types.ModuleType(name)
    result.__path__ = []
    vars(result).update(attrs)
    sys.modules[name] = result
    return result


class MediaType(Enum):
    MOVIE = '电影'
    TV = '电视剧'


@dataclass
class MediaInfo:
    type: object = MediaType.MOVIE
    tmdb_id: object = None
    douban_id: object = None
    title: str = ''
    year: object = None
    season: object = None
    seasons: dict = field(default_factory=dict)


class PluginBase:
    def __init__(self):
        self.data = {}

    def save_data(self, key, value):
        import copy
        self.data[key] = copy.deepcopy(value)

    def get_data(self, key):
        import copy
        return copy.deepcopy(self.data.get(key))


for name in ('app', 'app.chain', 'app.core', 'app.db', 'app.helper', 'app.schemas', 'app.utils'):
    module(name)
module('app.plugins', _PluginBase=PluginBase)
module('app.core.context', MediaInfo=MediaInfo, TorrentInfo=types.SimpleNamespace)
module('app.core.config', settings=types.SimpleNamespace(TZ='UTC'))
module('app.schemas.types', MediaType=MediaType)
module('app.log', logger=logging.getLogger('offline-filmwatchlist'))
for name, cls in (
    ('app.chain.download', 'DownloadChain'), ('app.chain.media', 'MediaChain'),
    ('app.chain.search', 'SearchChain'), ('app.db.downloadhistory_oper', 'DownloadHistoryOper'),
    ('app.db.site_oper', 'SiteOper'), ('app.helper.torrent', 'TorrentHelper'),
    ('app.helper.sites', 'SitesHelper'), ('app.utils.http', 'RequestUtils'),
):
    module(name, **{cls: Mock(name=cls)})
root = Path(__file__).resolve().parents[1] / 'plugins.v2' / 'filmwatchlist'
spec = importlib.util.spec_from_file_location('app.plugins.filmwatchlist', root / '__init__.py',
                                             submodule_search_locations=[str(root)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
