from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from mcp_platform import RuntimeConfig


def secret(name: str) -> str:
    inline, filename = os.environ.get(name, ""), os.environ.get(name + "_FILE", "")
    if inline and filename:
        raise ValueError(f"configure only one of {name} and {name}_FILE")
    return Path(filename).read_text().strip() if filename else inline.strip()


@dataclass
class Settings:
    database: str
    runtime: RuntimeConfig
    read_token: str = field(repr=False)
    write_token: str = field(repr=False)
    health_token: str = field(repr=False)
    accounting_token: str = field(repr=False)

    def __post_init__(self):
        tokens = (self.read_token, self.write_token, self.health_token, self.accounting_token)
        if not all(tokens) or len(set(tokens)) != len(tokens):
            raise ValueError("configure four nonempty distinct API read/write and source tokens")

    @classmethod
    def from_env(cls):
        runtime = RuntimeConfig.from_env("personal-records")
        runtime.allowed_hosts.extend(("personal-records", "192.168.31.201"))
        return cls(database=os.getenv("RECORDS_DATABASE", "/data/records.sqlite"), runtime=runtime,
            read_token=secret("RECORDS_API_READ_TOKEN"), write_token=secret("RECORDS_API_WRITE_TOKEN"),
            health_token=secret("RECORDS_HEALTH_TOKEN"), accounting_token=secret("RECORDS_ACCOUNTING_TOKEN"))
