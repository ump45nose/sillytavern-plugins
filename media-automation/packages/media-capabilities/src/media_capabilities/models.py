from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json


def stable_id(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass
class FileAsset:
    path: str
    size: int
    sha1: str = ""
    mtime_ns: int = 0
    device: int = 0
    inode: int = 0
    relative: str = ""
    episode: int | None = None

    def dump(self) -> dict:
        return asdict(self)


@dataclass
class MediaUnit:
    key: str
    kind: str
    title: str
    provider_ids: dict[str, str] = field(default_factory=dict)
    season: int | None = None
    expected_episodes: list[int] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    favored_by: list[str] = field(default_factory=list)
    runtime_seconds: float | None = None

    def dump(self) -> dict:
        return asdict(self)


@dataclass
class SeedRule:
    days: float = 30
    ratio: float = 1
    mode: str = "any"

    def __post_init__(self):
        import math
        if self.mode not in {"any", "all"} or not all(
                math.isfinite(float(v)) and float(v) >= 0 for v in (self.days, self.ratio)):
            raise ValueError("保种规则需要非负天数/分享率，mode 为 any 或 all")
        self.days, self.ratio = float(self.days), float(self.ratio)


@dataclass
class TorrentSnapshot:
    downloader: str
    info_hash: str
    site: str
    files: list[str]
    seeding_seconds: int | None
    ratio: float | None
    complete: bool
    rule: SeedRule = field(default_factory=SeedRule)
    retained: bool = False
    matched_files: list[str] = field(default_factory=list)
    source_files: list[dict] = field(default_factory=list)

    def dump(self) -> dict:
        return asdict(self)


@dataclass
class DiscTitle:
    id: int
    duration: float = 0
    chapters: int = 0
    size: int = 0
    segments: str = ""
    name: str = ""
    output_name: str = ""
    source_file: str = ""
    episode: int | None = None
    streams: list[dict] = field(default_factory=list)

    def dump(self) -> dict:
        return asdict(self)
