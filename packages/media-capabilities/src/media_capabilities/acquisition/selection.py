"""片单资源的可播放性检查与确定性质量排序。"""

from pathlib import PurePosixPath
import re
import unicodedata


DISC_TITLE = re.compile(
    r"(?i)(?:\b(?:ISO|BDMV|BD25|BD50|BD66|BD100|DVD5|DVD9|FULL[ ._-]?DISC)\b|原盘)"
)
REMUX_TITLE = re.compile(r"(?i)\bREMUX\b")
BLURAY_TITLE = re.compile(r"(?i)\b(?:UHD[ ._-]?)?BLU[ ._-]?RAY\b|\bBDRIP\b")
WEB_DL_TITLE = re.compile(r"(?i)\bWEB[ ._-]?DL\b")
WEB_RIP_TITLE = re.compile(r"(?i)\bWEB[ ._-]?RIP\b")
HDR_TITLE = re.compile(r"(?i)\b(?:DOVI|DOLBY[ ._-]?VISION|DV|HDR10\+?|HDR|HLG)\b")
AUDIO_TITLE = re.compile(r"(?i)\b(?:ATMOS|DTS[ ._-]?X|TRUEHD|DTS[ ._-]?HD|FLAC|DDP)\b")
EPISODE_FILE = re.compile(r"(?i)(?:S0*1[ ._-]*E0*(\d{1,3})|第0*(\d{1,3})[集话話])")
DISC_PARTS = {"bdmv", "certificate", "video_ts"}
DISC_SUFFIXES = {".iso", ".m2ts", ".mpls", ".bdmv", ".ifo", ".vob"}
VIDEO_SUFFIXES = {".mkv", ".mp4"}


def normalize_title(value: str) -> str:
    """统一标题形式，用于媒体身份候选的严格比较。"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", value or "").casefold() if ch.isalnum())


def quality_key(title: str, seeders: int = 0) -> tuple[int, int, int, int, int, int]:
    """按 Remux、分辨率、片源、HDR、音轨、做种数排序。"""
    text = title or ""
    remux = bool(REMUX_TITLE.search(text))
    if re.search(r"(?i)\b(?:2160p|4k|uhd)\b", text):
        resolution = 2160
    elif re.search(r"(?i)\b1080[pi]\b", text):
        resolution = 1080
    elif re.search(r"(?i)\b720[pi]\b", text):
        resolution = 720
    else:
        resolution = 0
    source = 3 if BLURAY_TITLE.search(text) else 2 if WEB_DL_TITLE.search(text) else 1 if WEB_RIP_TITLE.search(text) else 0
    return (int(remux), resolution, source, int(bool(HDR_TITLE.search(text))),
            int(bool(AUDIO_TITLE.search(text))), max(0, int(seeders or 0)))


def inspect_files(title: str, files: list[str], expected_episodes: set[int] | None = None) -> tuple[bool, str]:
    """检查候选文件确实是可直接播放的视频，剧集还须覆盖目标季。"""
    if DISC_TITLE.search(title or ""):
        return False, "标题标为原盘或光盘镜像"
    if not files:
        return False, "种子文件清单为空"
    paths = [PurePosixPath(str(name).replace("\\", "/")) for name in files]
    if any(set(part.casefold() for part in path.parts) & DISC_PARTS
           or path.suffix.casefold() in DISC_SUFFIXES for path in paths):
        return False, "包含原盘结构或镜像文件"
    videos = [path for path in paths if path.suffix.casefold() in VIDEO_SUFFIXES]
    if not videos:
        return False, "没有 MKV/MP4 视频文件"
    if expected_episodes is not None:
        found = set()
        for path in videos:
            match = EPISODE_FILE.search(path.name)
            if match:
                found.add(int(match.group(1) or match.group(2)))
        if not expected_episodes or not expected_episodes.issubset(found):
            return False, "不是可核实的第一季全集"
    return True, "可播放"
