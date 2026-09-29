"""Historical large-Markdown maintenance; not imported by the worker."""
import fcntl
import json
import os
from pathlib import Path
import re
from urllib.parse import quote
from .journal import literal
from .layout import paths, platform_root


def journal_path(cfg, platform):
    root = Path(cfg['download_dir']) if cfg.get('markdown_scope', 'platform') == 'combined' else platform_root(cfg, platform)
    return root / '收藏.md'


def append_entry(cfg, item, assets):
    target = journal_path(cfg, item['platform'])
    target.parent.mkdir(parents=True, exist_ok=True)
    key = f"{item['platform']}:{item['account']}:{item['item_id']}"
    start = f'<!-- favsync:{key}:start -->'
    end = f'<!-- favsync:{key}:end -->'
    naming = json.loads(item['locator']).get('naming', {})
    title = ' · '.join(str(x) for x in (item['platform'], naming.get('date'), naming.get('group'), naming.get('topic'),
                                       f"{item['account']}/{item['item_id']}") if x)
    lines = [start, '- **' + literal(title) + '**', '', '  ' + literal(item['body'].strip() or '（无正文）')]
    if item['platform'] == 'x':
        lines += ['', f"  [原帖](https://x.com/i/web/status/{item['item_id']})"]
    for asset in assets:
        media = paths(cfg, item, asset)
        url = quote(media.relative_to(target.parent).as_posix(), safe='/')
        suffix = media.suffix.lower()
        label = f"{asset['number']}"
        if suffix in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif'):
            link = f'![图片 {label}]({url})'
        elif suffix in ('.mp4', '.mov', '.webm', '.mkv', '.m4v'):
            link = f'[▶ 视频 {label}]({url})'
        else:
            link = f'[附件 {label}]({url})'
        lines += ['', '  ' + link]
    block = ('\n'.join(lines) + '\n' + end + '\n\n').encode()
    with target.open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        content = stream.read()
        # Completed block markers are the commit record, so a crash between the
        # file fsync and SQLite update cannot append a second copy on retry.
        if end.encode() in content:
            return False
        starts = list(re.finditer(rb'<!-- favsync:([a-z0-9_-]+:[A-Za-z0-9_-]+:[0-9]+):start -->', content))
        if starts:
            last = starts[-1]
            last_end = b'<!-- favsync:' + last.group(1) + b':end -->'
            if last_end not in content[last.end():]:
                stream.truncate(last.start())
                content = content[:last.start()]
        # Recover even a torn start marker; no generated text follows the last
        # completed block except whitespace or the next start marker.
        ends = list(re.finditer(rb'<!-- favsync:[a-z0-9_-]+:[A-Za-z0-9_-]+:[0-9]+:end -->\n', content))
        boundary = ends[-1].end() if ends else len('# 收藏\n\n'.encode())
        tail = content[boundary:].lstrip()
        if tail and (b'<!-- favsync:'.startswith(tail) or tail.startswith(b'<!-- favsync:')):
            stream.truncate(boundary)
            content = content[:boundary]
        stream.seek(0, os.SEEK_END)
        if not content:
            stream.write('# 收藏\n\n'.encode())
        stream.write(block)
        stream.flush()
        os.fsync(stream.fileno())
    return True
