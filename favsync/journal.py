"""Append-only, per-post Markdown with local media links and retry deduplication."""
import fcntl
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from .common import atomic_write
from .layout import paths, platform_root, telegram_stem


def journal_path(cfg, platform):
    root = Path(cfg['download_dir']) if cfg.get('markdown_scope', 'platform') == 'combined' else platform_root(cfg, platform)
    return root / '收藏.md'


def literal(text):
    text = html.escape(str(text), quote=False)
    return re.sub(r'([\\`*_\[\]{}])', r'\\\1', text).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>')


def write_item_markdown(cfg, item, media, *, stem=None):
    """Create one new-post Markdown beside the media; never rewrite old files."""
    root = platform_root(cfg, item["platform"])
    root.mkdir(parents=True, exist_ok=True)
    if stem is None:
        stem = telegram_stem(item)
    target = root / (stem + ".md")
    if target.exists():
        return target
    body = item["body"].strip()
    if not body:
        return None
    lines = ["# " + literal(stem), "", literal(body)]
    if item["platform"] == "x":
        lines.extend(["", f"[原帖](https://x.com/i/web/status/{item['item_id']})"])
    elif item["platform"] == "xhs":
        lines.extend(["", f"[原帖](https://www.xiaohongshu.com/explore/{item['item_id']})"])
    for index, path in enumerate(media, 1):
        path = Path(path)
        if not path.is_file() or not path.stat().st_size:
            raise OSError("media_missing")
        url = quote(path.relative_to(root).as_posix(), safe="/")
        if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"):
            lines.extend(["", f"![图片 {index}]({url})"])
        elif path.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
            lines.extend(["", f"[▶ 视频 {index}]({url})"])
    atomic_write(target, ("\n".join(lines) + "\n").encode("utf-8"))
    return target


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
