"""Offline fixture: consumers use the independent host through PluginManager."""
from host_stub import *

host = load_plugin('mediacapabilities', 'MediaCapabilities')()
host.init_plugin({'enabled': True})
PluginManager.registry['MediaCapabilities'] = host
load_plugin('filmwatchlist', 'FilmWatchlist')
