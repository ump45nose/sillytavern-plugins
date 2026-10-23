"""Explicit season labels; sequel numbers and years are never season evidence."""
import re
import unicodedata

SEASON_LABEL = re.compile(
    r"第\s*([0-9一二三四五六七八九十百零〇两]+)\s*季|"
    r"(?<![A-Za-z0-9])(?:season\s*|s)([0-9]{1,3})(?![0-9]|[Ee][0-9])", re.I)


def season_number(value):
    value = str(value).replace('两', '二').replace('〇', '零')
    if value.isdecimal():
        return int(value)
    digits = {c: n for n, c in enumerate('零一二三四五六七八九')}
    total = current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in ('十', '百'):
            total += (current or 1) * (10 if char == '十' else 100)
            current = 0
        else:
            raise ValueError('无效季数')
    return total + current


def split_season_title(title):
    text = unicodedata.normalize('NFKC', str(title or '')).strip()
    labels = list(SEASON_LABEL.finditer(text))
    seasons = {season_number(m[1] or m[2]) for m in labels}
    if len(seasons) > 1 or any(s < 1 or s > 999 for s in seasons):
        raise ValueError('季数冲突或无效')
    base = SEASON_LABEL.sub('', text).strip(' .:-_')
    return base, next(iter(seasons), None)
