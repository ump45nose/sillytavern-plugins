"""Download profiles and explicit subtitle evidence; no network or host imports."""
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import DownloadTarget, SubtitleEvidence
from .quality_selection import rank_candidates
from .selection import inspect_files, quality_key

EPISODE = re.compile(r"(?i)(?<![A-Z0-9])S(\d{1,3})[ ._-]*E(\d{1,3})"
                     r"((?:(?:[ ._]*E|[ ._]*-[ ._]*E?)\d{1,3})*)(?![A-Z0-9])")
EPISODE_TAIL = re.compile(r"(?i)([ ._]*E|[ ._]*-[ ._]*E?)(\d{1,3})")
CHINESE = re.compile(r"(?i)中文字幕|简[繁体]*[中字幕]|繁[体]*[中字幕]|中英[双字幕]*|\b(?:CHS|CHT|CHI|ZHO|zh(?:[-_.](?:CN|TW|Hans|Hant))?)\b|Chinese[ ._-]*subtitles?")


def subtitle_evidence(text: str = "", files=()) -> SubtitleEvidence:
    for name in files:
        if PurePosixPath(name).suffix.lower() in (".srt", ".ass", ".ssa", ".sup", ".vtt") \
                and CHINESE.search(name) and "forced" not in name.lower():
            return SubtitleEvidence("sidecar", True, "资源包含明确命名的中文字幕文件")
    # MediaInfo language rows can provide a stronger declaration than a release title.
    if re.search(r"(?is)(?:Text\s*#?\d*|字幕)[^\n]*(?:\n[^\n]*){0,12}?Language\s*:\s*(?:Chinese|中文)", text):
        return SubtitleEvidence("mediainfo", True, "页面 MediaInfo 声明中文字幕；尚未实测轨道")
    if CHINESE.search(text) and not re.search(r"(?i)无中文字幕|无中字|no chinese|forced.only", text):
        return SubtitleEvidence("source_claim", True, "站点或资源标题声明中文字幕；尚未实测轨道")
    return SubtitleEvidence()


def inspect_target(title: str, files, target: DownloadTarget):
    okay, reason = inspect_files(title, list(files))
    if not okay:
        raise ValueError(reason)
    if target.scope == "movie":
        if sum(PurePosixPath(name.replace("\\", "/")).suffix.lower() in (".mkv", ".mp4")
               for name in files) != 1:
            raise ValueError("电影资源必须只包含一个 MKV/MP4 视频")
        return
    found, unknown = set(), False
    for name in files:
        if PurePosixPath(name).suffix.lower() not in (".mkv", ".mp4"):
            continue
        matches = list(EPISODE.finditer(name))
        if not matches:
            # Chinese episode names are usable only when their season is explicit.
            season = re.search(r"(?i)(?:\bS(\d{1,3})\b|第(\d+)季)", name)
            episode = re.search(r"第(\d+)[集话話]", name)
            if season and episode:
                found.add((int(season[1] or season[2]), int(episode[1])))
            else:
                unknown = True
            continue
        for match in matches:
            season, previous = int(match[1]), int(match[2])
            found.add((season, previous))
            for separator, number in EPISODE_TAIL.findall(match[3]):
                last = int(number)
                if '-' in separator:
                    if last < previous or last - previous > 100:
                        raise ValueError("文件集序范围无效")
                    found.update((season, e) for e in range(previous, last + 1))
                else:
                    found.add((season, last))
                previous = last
    if not target.expected.issubset(found):
        raise ValueError("资源未覆盖目标季集")
    if target.scope in ("season", "episode") and (unknown or found != set(target.expected)):
        raise ValueError("资源包含目标范围之外或无法确认集序的视频")


@dataclass(frozen=True)
class ProfileSettings:
    near_size_ratio: float = 0.10
    movie_limit_gib: float = 35
    episode_limit_gib: float = 8


def select_candidates(candidates, target: DownloadTarget, policy: str,
                      settings: ProfileSettings = ProfileSettings()):
    warnings = []
    if policy == "subtitle":
        known = [c for c in candidates if c.evidence.get("subtitles", {}).get("chinese")]
        if known:
            return rank_candidates(known, settings.near_size_ratio), warnings
        warnings.append("没有明确中文字幕证据，已降级到均衡下载")
        policy = "balanced"
    if policy == "quality":
        return rank_candidates(candidates, settings.near_size_ratio), warnings
    budget = (settings.movie_limit_gib if target.scope == "movie" else
              settings.episode_limit_gib * len(target.expected)) * 1024 ** 3
    allowed = [c for c in candidates if c.video_bytes > 0 and c.total_bytes <= budget
               and not quality_key(c.title)[0] and quality_key(c.title)[1] in (1080, 2160)]
    def key(c):
        _, resolution, source, *_ = quality_key(c.title)
        return (-resolution, -source, c.video_bytes,
                -int(c.evidence.get("seeders", 0)), not c.public, c.candidate_id)
    return sorted(allowed, key=key), warnings
