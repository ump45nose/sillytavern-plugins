"""Normalize only at host/backend boundaries; persisted media keys stay unchanged."""


def normalize_media_type(value) -> str:
    value = getattr(value, 'value', value)
    if value in ('movie', '电影'):
        return 'movie'
    if value in ('tv', 'tv_show', '电视剧'):
        return 'tv'
    raise ValueError('未知媒体类型，拒绝选择媒体目录')
