"""Static source definitions shared by configuration, workers, CLI and reports."""
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True)
class SourceSpec:
    name: str
    platform: str
    adapter: str
    label: str
    date_section: str = ""
    baseline: bool = False
    markdown: bool = False
    metadata: bool = False


SOURCE_SPECS = (
    SourceSpec("telegram", "telegram", "telegram", "Telegram", "telegram"),
    SourceSpec("telegram_notice", "telegram_notice", "telegram", "Telegram Bot 投递", markdown=True),
    SourceSpec("x_bookmarks", "x", "x", "X 书签", "x_bookmarks", markdown=True),
    SourceSpec("x_likes", "x", "x", "X 点赞", baseline=True),
    SourceSpec("eh_favorites", "eh", "eh", "EH 收藏", baseline=True),
    SourceSpec("xhs_creators", "xhs", "xhs", "陪伴作者素材", metadata=True),
    SourceSpec("xhs_favorites", "xhs", "xhs", "小红书收藏", markdown=True),
    SourceSpec("xhs_likes", "xhs", "xhs", "小红书点赞"),
    SourceSpec("pixiv_art_public", "pixiv", "pixiv", "Pixiv 公开图片", "pixiv", baseline=True),
    SourceSpec("pixiv_art_private", "pixiv", "pixiv", "Pixiv 私密图片", "pixiv", baseline=True),
    SourceSpec("pixiv_novel_public", "pixiv", "pixiv", "Pixiv 公开小说", "pixiv", baseline=True),
    SourceSpec("pixiv_novel_private", "pixiv", "pixiv", "Pixiv 私密小说", "pixiv", baseline=True),
    SourceSpec("wallabag_entries", "wallabag", "wallabag", "Wallabag"),
    SourceSpec("film_watchlist", "film", "films", "B 站影视片单", metadata=True),
)
REGISTRY = {spec.name: spec for spec in SOURCE_SPECS}
SOURCES = tuple(REGISTRY)
SOURCE_PLATFORM = {spec.name: spec.platform for spec in SOURCE_SPECS}
SOURCE_LABELS = {spec.name: spec.label for spec in SOURCE_SPECS}

# Factories are lazy: an API/status process never imports the download stack.
ADAPTER_TYPES = {
    "telegram": ("adapters", "TelegramAdapter", False),
    "x": ("adapters", "XAdapter", False),
    "eh": ("adapters_ext", "EhAdapter", True),
    "xhs": ("adapters_ext", "XhsAdapter", True),
    "pixiv": ("adapters_pixiv_wallabag", "PixivAdapter", True),
    "wallabag": ("adapters_pixiv_wallabag", "WallabagAdapter", True),
    "films": ("film_watchlist", "FilmWatchlistAdapter", False),
}


def make_adapter(name, cfg, store):
    module, symbol, needs_store = ADAPTER_TYPES[name]
    adapter = getattr(import_module("." + module, __package__), symbol)
    return adapter(cfg, store) if needs_store else adapter(cfg)


@dataclass
class ScanResult:
    records: list
    cursor: int | None = None
    reason: str = "end"
    # Opaque adapter checkpoint, committed with records by Store.apply_scan.
    continuation: dict | None = None

    @property
    def complete(self):
        return self.reason in ("end", "seen_boundary")

    def __iter__(self):
        # Keep the existing adapter tuple contract during incremental adoption.
        yield self.records
        yield self.cursor

    @classmethod
    def coerce(cls, result):
        return result if isinstance(result, cls) else cls(*result)
