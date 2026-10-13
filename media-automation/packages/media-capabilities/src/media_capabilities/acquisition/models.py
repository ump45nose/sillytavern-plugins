"""Host-neutral requests, targets and redacted resource facts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class AcquisitionRequest:
    title: str = ""
    year: int | None = None
    media_type: Literal["movie", "tv"] | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    candidate_id: str | None = None
    scope: Literal["season", "episode", "series"] = "season"
    season: int | None = None
    episode: int | None = None
    policy: Literal["quality", "subtitle", "balanced"] = field(default="quality", metadata={
        "description": "默认使用 quality（质量优先）。未指定偏好时省略此参数或使用 quality；"
                       "仅当用户明确要求均衡／控制体积时使用 balanced，明确要求中文字幕时使用 subtitle。"})
    request_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.title, str):
            raise ValueError("title 必须是字符串")
        for name in ('imdb_id', 'candidate_id', 'request_id'):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(name + " 必须是字符串")
        for name in ('tmdb_id', 'year'):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(name + " 必须是正整数")
        if self.imdb_id and not re.fullmatch(r'tt\d+', self.imdb_id):
            raise ValueError("imdb_id 必须是 tt 开头的媒体 ID")
        if self.media_type not in (None, "movie", "tv"):
            raise ValueError("media_type 必须是 movie 或 tv")
        if self.scope not in ("season", "episode", "series"):
            raise ValueError("scope 必须是 season、episode 或 series")
        if self.policy not in ("quality", "subtitle", "balanced"):
            raise ValueError("policy 必须是 quality、subtitle 或 balanced")
        if not any((self.title.strip(), self.tmdb_id, self.imdb_id, self.candidate_id)):
            raise ValueError("需要片名、媒体 ID 或搜索返回的候选引用")
        if self.tmdb_id and not self.media_type:
            raise ValueError("使用 TMDB ID 时必须指定 media_type")
        if self.season is None:
            if self.scope == 'episode':
                raise ValueError("episode 范围必须明确指定季号和集号")
            object.__setattr__(self, 'season', 1)
        if isinstance(self.season, bool) or not isinstance(self.season, int) or self.season < 1:
            raise ValueError("season 必须是正整数")
        if self.scope == "episode" and (isinstance(self.episode, bool)
                or not isinstance(self.episode, int) or self.episode < 1):
            raise ValueError("episode 范围必须提供正整数集号")
        if self.request_id and (len(self.request_id) > 128 or not self.request_id.isascii()):
            raise ValueError("request_id 必须是最多 128 字符的 ASCII 标识")

    @classmethod
    def parse(cls, data: dict):
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError("未知参数：" + ", ".join(sorted(unknown)))
        return cls(**data)


@dataclass(frozen=True)
class MediaIdentity:
    title: str
    media_type: str | None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    year: int | None = None
    aliases: tuple[str, ...] = ()
    episodes: tuple[tuple[int, int], ...] = ()
    ended: bool = False
    exact_match: bool = True


@dataclass(frozen=True)
class DownloadTarget:
    media: MediaIdentity
    scope: str
    expected: frozenset[tuple[int, int]] = frozenset()

    @classmethod
    def build(cls, media: MediaIdentity, request: AcquisitionRequest):
        if media.media_type == "movie":
            return cls(media, "movie")
        if request.scope == "series" and not media.ended:
            raise ValueError("整剧下载只接受已核实完结的剧集")
        expected = frozenset((s, e) for s, e in media.episodes if s > 0 and
                            (request.scope == "series" or s == request.season) and
                            (request.scope != "episode" or e == request.episode))
        if not expected or (request.scope == "episode" and len(expected) != 1):
            raise ValueError("无法核实目标季集信息")
        return cls(media, request.scope, expected)


@dataclass(frozen=True)
class SearchTarget:
    """Name-based search without asserting a verified identity or episode list."""
    media: MediaIdentity
    scope: str
    season: int | None = None
    expected: frozenset[tuple[int, int]] = frozenset()

    @classmethod
    def from_request(cls, request: AcquisitionRequest):
        return cls(MediaIdentity(request.title.strip(), request.media_type,
                                 year=request.year, exact_match=False),
                   'movie' if request.media_type == 'movie' else request.scope,
                   request.season if request.media_type != 'movie' else None)


@dataclass(frozen=True)
class SubtitleEvidence:
    kind: str = "unknown"  # source_claim, mediainfo, sidecar, unknown
    chinese: bool = False
    text: str = ""


@dataclass
class ResourceCandidate:
    candidate_id: str
    source_id: str
    title: str
    size_bytes: int | None = None
    seeders: int = 0
    subtitles: SubtitleEvidence = field(default_factory=SubtitleEvidence)
    # Native contexts and links never cross a public response boundary.
    native: Any = field(default=None, repr=False)

    def public_dict(self):
        return {"candidate_id": self.candidate_id, "source_id": self.source_id,
                "title": self.title, "size_bytes": self.size_bytes,
                "seeders": self.seeders, "subtitles": asdict(self.subtitles)}


@dataclass
class SourcePage:
    status: str
    candidates: list[ResourceCandidate] = field(default_factory=list)
    next_cursor: str | None = None
    reason: str = ""


class SourceAdapter(Protocol):
    source_id: str
    public_source: bool
    def search(self, target: DownloadTarget | SearchTarget, cursor: str | None = None) -> SourcePage: ...
    def resolve(self, candidate: ResourceCandidate, target: DownloadTarget): ...
    def health(self) -> dict: ...


class IdentityPort(Protocol):
    def identify(self, request: AcquisitionRequest) -> list[MediaIdentity]: ...


class DownloaderAdapter(Protocol):
    def submit(self, candidate, target: DownloadTarget) -> dict: ...
    def status(self, record: dict) -> dict: ...
