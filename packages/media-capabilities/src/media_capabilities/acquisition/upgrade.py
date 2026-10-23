"""Host-neutral version comparison for library wash/upgrade workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePath
from typing import Literal

from .quality_selection import MediaCandidate
from .selection import quality_key

ResolutionStrategy = Literal["tiered", "resolution_size"]


@dataclass(frozen=True)
class VersionFacts:
    title: str
    video_bytes: int
    resolution: int = 0
    tier: int = 0
    hdr: bool = False
    source: str = "library"

    def dump(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UpgradeDecision:
    action: Literal["keep", "upgrade", "unknown"]
    reason: str
    current: VersionFacts
    best: VersionFacts | None = None
    candidate_id: str = ""
    source: str = ""

    @property
    def upgrade(self) -> bool:
        return self.action == "upgrade"

    @property
    def equivalent(self) -> bool:
        return self.action == "keep"

    def dump(self) -> dict:
        data = asdict(self)
        data["upgrade"] = self.upgrade
        data["equivalent"] = self.equivalent
        return data


def _probe_resolution(probe: dict | None) -> int:
    if not probe:
        return 0
    videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not videos:
        return 0
    stream = max(videos, key=lambda s: int(s.get("width") or 0) * int(s.get("height") or 0))
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if width >= 3800 or height >= 2100:
        return 2160
    if width >= 1900 or height >= 1060:
        return 1080
    if width >= 1260 or height >= 700:
        return 720
    return height if height > 0 else 0


def _probe_hdr(probe: dict | None) -> bool:
    if not probe:
        return False
    for stream in probe.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        transfer = str(stream.get("color_transfer") or "").casefold()
        primaries = str(stream.get("color_primaries") or "").casefold()
        if transfer in {"smpte2084", "arib-std-b67"} or "bt2020" in primaries:
            return True
        if any("dovi" in str(item).casefold() or "dolby vision" in str(item).casefold()
               for item in stream.get("side_data_list", []) or []):
            return True
    return False


def _title_resolution(title: str) -> int:
    return quality_key(title)[1]


def _candidate_title(candidate: MediaCandidate) -> str:
    return " ".join((candidate.title, *(PurePath(p).name for p in candidate.files)))


def facts_from_library(title: str, video_bytes: int, probe: dict | None = None) -> VersionFacts:
    if video_bytes <= 0:
        raise ValueError("当前媒体大小必须为正数")
    parsed = quality_key(title)
    actual_resolution = _probe_resolution(probe)
    resolution = actual_resolution or parsed[1]
    decorated = title
    if resolution and not _title_resolution(decorated):
        decorated += f" {resolution}p"
    if _probe_hdr(probe) and not parsed[3]:
        decorated += " HDR"
    synthetic = MediaCandidate("library", decorated, video_bytes, video_bytes, "library")
    return VersionFacts(title, video_bytes, resolution, synthetic.tier,
                        bool(quality_key(decorated)[3]), "library")


def facts_from_candidate(candidate: MediaCandidate) -> VersionFacts:
    title = _candidate_title(candidate)
    synthetic = MediaCandidate(candidate.source, title, candidate.video_bytes,
                               candidate.total_bytes, candidate.candidate_id,
                               evidence=candidate.evidence)
    return VersionFacts(candidate.title, int(candidate.video_bytes),
                        _title_resolution(title), synthetic.tier,
                        bool(quality_key(title)[3]), candidate.source)


def _best_tiered(candidates: list[MediaCandidate]) -> MediaCandidate:
    return max(candidates, key=lambda c: (
        c.tier, c.video_bytes, c.detail_key, int(c.public), c.candidate_id))


def _best_resolution_size(candidates: list[MediaCandidate]) -> MediaCandidate:
    return max(candidates, key=lambda c: (
        _title_resolution(_candidate_title(c)), c.video_bytes,
        int(c.evidence.get("cnsub", False)), int(c.evidence.get("hd", False)),
        int(c.public), c.candidate_id))


def decide_upgrade(current: VersionFacts, candidates: list[MediaCandidate], *,
                   strategy: ResolutionStrategy = "tiered",
                   near_size_ratio: float = 0.10) -> UpgradeDecision:
    """Compare one installed version to verified candidates."""
    ratio = float(near_size_ratio)
    if ratio < 0 or ratio > 0.5:
        raise ValueError("near_size_ratio 必须在 0 到 0.5 之间")
    usable = [c for c in candidates if c.video_bytes > 0]
    if not usable:
        return UpgradeDecision("unknown", "没有可核实的候选版本", current)

    if strategy == "tiered":
        chosen = _best_tiered(usable)
        best = facts_from_candidate(chosen)
        if best.tier > current.tier:
            return UpgradeDecision("upgrade", "候选质量档位更高", current, best,
                                   chosen.candidate_id, chosen.source)
        if best.tier < current.tier:
            return UpgradeDecision("keep", "当前版本质量档位更高", current, best,
                                   chosen.candidate_id, chosen.source)
    elif strategy == "resolution_size":
        chosen = _best_resolution_size(usable)
        best = facts_from_candidate(chosen)
        if best.resolution and current.resolution:
            if best.resolution > current.resolution:
                return UpgradeDecision("upgrade", "候选可识别分辨率更高", current, best,
                                       chosen.candidate_id, chosen.source)
            if best.resolution < current.resolution:
                return UpgradeDecision("keep", "当前版本分辨率更高", current, best,
                                       chosen.candidate_id, chosen.source)
    else:
        raise ValueError("未知洗版比较策略")

    gain = (best.video_bytes - current.video_bytes) / max(
        best.video_bytes, current.video_bytes)
    if gain > ratio:
        return UpgradeDecision("upgrade", "同档候选视频体积明显更大", current, best,
                               chosen.candidate_id, chosen.source)
    return UpgradeDecision("keep", "当前版本与最佳候选处于同档且体积接近", current, best,
                           chosen.candidate_id, chosen.source)


def is_4k(probe: dict | None, title: str = "") -> bool:
    return (_probe_resolution(probe) or _title_resolution(title)) >= 2160
