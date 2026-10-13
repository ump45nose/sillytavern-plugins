"""Across-source quality comparison. Indexers never make download decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .selection import quality_key


@dataclass
class MediaCandidate:
    source: str  # pt, public_bt, 115_share
    title: str
    video_bytes: int
    total_bytes: int
    candidate_id: str
    info_hash: str = ""
    link: str = ""
    torrent_content: bytes | None = None
    context: Any = None
    files: tuple[str, ...] = ()
    file_ids: tuple[int, ...] = ()
    evidence: dict = field(default_factory=dict)

    @property
    def public(self) -> bool:
        return self.source != "pt"

    @property
    def tier(self) -> int:
        remux, resolution, source, *_ = quality_key(self.title)
        if remux and resolution >= 2160:
            return 600
        if remux and resolution >= 1080:
            return 500
        if source >= 3 and resolution >= 2160:
            return 400
        if source >= 3 and resolution >= 1080:
            return 300
        if source == 2 and resolution >= 2160:
            return 200
        if source == 2 and resolution >= 1080:
            return 100
        return 90 if resolution >= 2160 else 80 if resolution >= 1080 else 70 if resolution >= 720 else 0

    @property
    def detail_key(self) -> tuple[int, int, int]:
        _, _, _, hdr, audio, seeders = quality_key(self.title)
        return hdr, audio, seeders


def rank_candidates(candidates: list[MediaCandidate], near_size_ratio: float = 0.10) -> list[MediaCandidate]:
    """Choose the larger file in a tier; prefer public when sizes are close."""
    ratio = max(0.0, min(float(near_size_ratio), 0.5))
    tiers = sorted({item.tier for item in candidates if item.video_bytes > 0}, reverse=True)
    ranked: list[MediaCandidate] = []
    for tier in tiers:
        public = sorted((item for item in candidates if item.tier == tier and item.public),
                        key=lambda item: (item.video_bytes, item.detail_key, item.candidate_id), reverse=True)
        pt = sorted((item for item in candidates if item.tier == tier and not item.public),
                    key=lambda item: (item.video_bytes, item.detail_key, item.candidate_id), reverse=True)
        while public or pt:
            if not public:
                ranked.append(pt.pop(0))
            elif not pt:
                ranked.append(public.pop(0))
            else:
                a, b = public[0], pt[0]
                difference = abs(a.video_bytes - b.video_bytes) / max(a.video_bytes, b.video_bytes)
                if difference <= ratio or a.video_bytes > b.video_bytes:
                    ranked.append(public.pop(0))
                else:
                    ranked.append(pt.pop(0))
    return ranked
