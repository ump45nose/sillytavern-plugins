from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import digest

SCHEMA_VERSION = 1
BLOCK_CHARS = 8000
PAGE_BYTES = 256 * 1024


def object_id(processor: str, source: str, scope_key: str) -> str:
    return digest(["hub-content", processor, source, scope_key])


@dataclass
class ContentBlock:
    key: str
    type: str
    text: str
    refs: list[dict]
    metadata: dict = field(default_factory=dict)

    def value(self, ordinal: int) -> dict:
        return dict(key=self.key, ordinal=ordinal, type=self.type, text=self.text,
                    refs=self.refs, metadata=self.metadata)


@dataclass
class ProcessedContent:
    type: str
    variant: str
    title: str
    preview: str
    blocks: list[ContentBlock]
    metadata: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    summary: str | None = None
    coverage: dict = field(default_factory=lambda: {"body": "complete"})
