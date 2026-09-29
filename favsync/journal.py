"""Append-only, per-post Markdown with local media links and retry deduplication."""
import html
import re
from pathlib import Path
from urllib.parse import quote

from .common import atomic_write
from .layout import platform_root, telegram_stem


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
