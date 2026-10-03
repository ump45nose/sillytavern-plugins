"""Compatible record persistence and immutable identity facts. No new state store."""
from datetime import datetime


def source_snapshot(item: dict) -> dict:
    return {key: item.get(key) for key in
            ('title', 'release_year', 'release_date', 'country', 'media_type')}


def pending_record(record: dict) -> bool:
    return record.get('status') != '已完成' and bool(
        record.get('task_state') in ('SUBMITTING', 'SUBMITTED')
        or record.get('download_hash') or record.get('library_ready')
        or record.get('status') == '待写回')


def media_snapshot(media, season: int | None) -> dict:
    """Persist enough verified identity to observe without re-running metadata search."""
    return {'title': getattr(media, 'title', None),
            'year': getattr(media, 'year', None),
            'media_type': getattr(media.type, 'value', media.type),
            'tmdb_id': media.tmdb_id, 'douban_id': media.douban_id,
            'season': season,
            'expected_episodes': sorted(expected_episodes(media, season) or [])}


def expected_episodes(media, season: int | None) -> set[int] | None:
    """剧集仅接受可核实的整季包，电影不需要集数约束。"""
    if season is None:
        return None
    seasons = media.seasons or {}
    episodes = seasons.get(season) or seasons.get(str(season)) or []
    try:
        return {int(episode) for episode in episodes}
    except (TypeError, ValueError):
        return set()


def store(self, records: dict, film_id: int, **values):
    """持久化单条处理状态和候选证据。"""
    key = str(film_id)
    record = {**records.get(key, {}), "film_id": film_id,
              "updated_at": datetime.now().isoformat(timespec="seconds"), **values}
    records[key] = record
    self.save_data("records", records)
