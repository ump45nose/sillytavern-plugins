"""验证元数据首次空响应后能在无人工 ID 的情况下恢复识别。"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.plugins.filmwatchlist import FilmWatchlist
from app.schemas.types import MediaType


candidate = SimpleNamespace(
    type=MediaType.MOVIE, year="2025", title="罪人", original_title=None,
    names=[], tmdb_id=None, douban_id="36742579", bangumi_id=None,
)
detail = SimpleNamespace(
    type=MediaType.MOVIE, year="2025", title="罪人", original_title="Sinners",
    names=[], tmdb_id=None, douban_id="36742579", release_date="2025-04-16",
    first_air_date=None, production_countries=[{"name": "美国"}], origin_country=[],
)
chain = Mock()
chain.search.side_effect = [(None, []), (None, []), (SimpleNamespace(name="罪人"), [candidate])]
chain.recognize_media.return_value = detail
with patch("app.plugins.filmwatchlist.MediaChain", return_value=chain), \
        patch("app.plugins.filmwatchlist.sleep") as pause:
    media, season, error = FilmWatchlist._identify({
        "title": "罪人", "release_year": 2025, "country": "美国", "media_type": "movie",
    })
assert media is detail and season is None and not error
assert chain.search.call_count == 3 and pause.call_count == 2
print("identify retry smoke: OK")
