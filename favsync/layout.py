"""Shared flat media layout beneath the single container download root."""
import json
import re
from pathlib import Path



def component(value, limit=72):
    value = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', str(value))
    value = re.sub(r'\s+', ' ', value).strip(' .')
    return value.encode('utf-8')[:limit].decode('utf-8', 'ignore').rstrip(' .')


def telegram_stem(item):
    naming = json.loads(item['locator']).get('naming', {})
    tags = ''.join(tag.replace('#', '') for tag in naming.get('tags', []))
    parts = []
    if tags:
        parts.append(component(tags, 48))
    parts.append(component(naming.get('group') or ('作者未知' if item['platform'] == 'x' else '收藏夹'), 72))
    if naming.get('topic'):
        parts.append(component(naming['topic'], 48))
    parts.append(component(naming.get('date') or '日期未知', 16))
    # The account and message ID make same-day files collision-safe, including
    # two accounts saving the same forwarded message.
    return '_'.join(parts) + '_' + item['account'] + '_' + item['item_id']


def platform_root(cfg, platform):
    if not re.fullmatch(r'[a-z][a-z0-9_-]*', platform):
        raise ValueError('invalid platform directory')
    if platform == 'xhs' and cfg.get('xhs', {}).get('output_dir'):
        return Path(cfg['xhs']['output_dir'])
    if platform == 'eh' and cfg.get('eh', {}).get('output_dir'):
        return Path(cfg['eh']['output_dir'])
    name = {'telegram': 'Telegram', 'x': 'Twitter', 'xhs': 'Xiaohongshu'}.get(platform, platform.capitalize())
    return Path(cfg['download_dir']) / name


def paths(cfg, item, asset=None):
    if asset is None:
        return platform_root(cfg, item['platform']) / '收藏.md'
    if item['platform'] in ('telegram', 'x'):
        root = platform_root(cfg, item['platform'])
        stem = telegram_stem(item)
        # Account labels may be 64 bytes. Bound the human-readable prefix so
        # the complete filename always fits the usual 255-byte filesystem limit.
        suffix = '_' + item['account'] + '_' + item['item_id']
        human = stem[:-len(suffix)]
        stem = component(human, 230 - len(suffix.encode())) + suffix
        name = stem + ((f"_{asset['number']:03d}" if asset['number'] > 1 else '') + Path(asset['filename']).suffix if asset else '')
        return root / (name + ('' if asset else '.txt'))
    root = platform_root(cfg, item['platform']) / item['account'] / item['item_id']
    return root / (asset['filename'] if asset else 'text.txt')
