"""Platform-owned invocation contract; importing it loads no providers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Task:
    platform: str
    directory: Path
    adapter: str
    timeout: float
    environment: frozenset[str] = frozenset()
    browser: bool = False
    configure: Callable | None = None
    command: Callable | None = None
    validate: Callable | None = None
    result_partition: Callable | None = None
    browser_recovery_reasons: frozenset[str] = frozenset()
