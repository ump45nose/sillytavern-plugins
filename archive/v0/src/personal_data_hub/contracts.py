from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


def instant(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)  # 旧 SQLite 的时间是 UTC。
    return result.astimezone(UTC)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass
class Asset:
    name: str
    path: Path | None = None
    content: bytes | None = None
    media_type: str = "application/octet-stream"


@dataclass
class Record:
    external_id: str
    kind: str
    raw: dict[str, Any]
    normalized: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None
    updated_at: datetime | None = None
    timezone: str = "Asia/Shanghai"
    assets: list[Asset] = field(default_factory=list)


@dataclass
class Batch:
    records: list[Record] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)
    next_cursor: dict[str, Any] | None = None
    # 仅完整、权威的全量清单可以用缺失 ID 推断删除。
    authoritative: bool = False
    seen_ids: list[str] | None = None


class Adapter(Protocol):
    def collect(self, cursor: dict[str, Any], since: datetime | None = None) -> Iterable[Batch]: ...
