"""Pure policies shared by archive and disc preparation."""
import math

from .models import DiscTitle, MediaUnit, TorrentSnapshot


def complete_unit(unit: MediaUnit) -> bool:
    if not unit.items or any(not row.get("path") for row in unit.items):
        return False
    if unit.kind == "movie":
        return len(unit.items) == 1
    actual = [row.get("episode") for row in unit.items]
    return bool(unit.expected_episodes) and len(set(actual)) == len(actual) and \
        set(actual) == set(unit.expected_episodes)


def seed_decision(torrent: TorrentSnapshot, high_ratio: float = 2,
                  high_days: float = 30) -> tuple[bool, bool]:
    """Returns archive eligibility and persistent source-retention decision."""
    seconds, ratio = torrent.seeding_seconds, torrent.ratio
    if (not torrent.complete or not torrent.site or seconds is None or ratio is None
            or seconds < 0 or not math.isfinite(ratio) or ratio < 0):
        return False, torrent.retained
    days = seconds / 86400
    tests = (days >= torrent.rule.days, ratio >= torrent.rule.ratio)
    eligible = all(tests) if torrent.rule.mode == "all" else any(tests)
    retained = torrent.retained or (days <= high_days and ratio >= high_ratio)
    return eligible, retained


def select_titles(titles: list[dict], kind: str, runtime: float | None = None,
                  episodes: list[int] | None = None) -> tuple[list[dict], str]:
    """Automatic selection requires a unique feature or explicit episode mapping.

    Duration/chapters/size rank recommendations, rather than silently choosing
    between editions. Identical segment sequences collapse duplicate playlists.
    """
    unique: dict[object, DiscTitle] = {}
    for raw in titles:
        title = DiscTitle(**raw)
        if title.duration <= 0:
            continue
        key = (title.segments, round(title.duration)) if title.segments else ("id", title.id)
        old = unique.get(key)
        if old is None or (len(title.streams), title.chapters, title.size) > (
                len(old.streams), old.chapters, old.size):
            unique[key] = title
    candidates = sorted(unique.values(), key=lambda t: (-t.chapters, -t.size, t.id))
    if kind == "tv":
        expected = set(episodes or [])
        mapped = [t for t in candidates if t.episode in expected]
        if expected and len(mapped) == len(expected) and {t.episode for t in mapped} == expected:
            return [t.dump() for t in sorted(mapped, key=lambda t: t.episode)], ""
        return [], "剧集标题与集序无法唯一对应，请人工指定"
    if runtime and runtime > 0:
        candidates = [t for t in candidates if abs(t.duration-runtime) <= max(180, runtime*.05)]
    else:
        candidates = [t for t in candidates if t.duration >= 1200]
    if len(candidates) == 1:
        return [candidates[0].dump()], ""
    return [], "主片不唯一或缺少可靠时长，请人工选择标题"
